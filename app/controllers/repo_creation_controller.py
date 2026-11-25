"""repo_creation_controller.py

Create a repository with a preset setup in one step (issue #38).

GitHub only lets a *user* access token create repositories in a personal account, so the
creation itself runs with the signed-in user's token (obtained just in time through the
OAuth flow and never stored). The form's option lists use the installation token.
"""
import re
import time
import logging
from urllib.parse import quote
from app.controllers.repo_controller import github_api

NAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
FULL_NAME_PATTERN = re.compile(r'^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$')
LICENSE_KEY_PATTERN = re.compile(r'^[a-z0-9.-]{1,40}$')
MAX_DESCRIPTION_LENGTH = 350

# Default branch protection applied when requested
BRANCH_PROTECTION = {
    'required_status_checks': None,
    'enforce_admins': False,
    'required_pull_request_reviews': {'required_approving_review_count': 1},
    'restrictions': None,
    'allow_force_pushes': False,
    'allow_deletions': False,
}

# Generating from a template is asynchronous: the default branch can take a moment to appear
PROTECTION_ATTEMPTS = 3
PROTECTION_RETRY_SECONDS = 2


def get_form_options(access_token):
    """
    .gitignore templates and licenses for the form. Missing lists just hide those options.
    Returns {'gitignore_templates': [names], 'licenses': [{'key', 'name'}]}.
    """
    gitignores, _ = github_api('GET', '/gitignore/templates', access_token)
    licenses, _ = github_api('GET', '/licenses', access_token)
    return {
        'gitignore_templates': gitignores or [],
        'licenses': [{'key': l['key'], 'name': l['name']} for l in (licenses or []) if 'key' in l],
    }


def validate_new_repository(form, owner, owner_type, user_login, templates, label_sources, options):
    """
    Check the "new repository" form.

    templates: full names of template repositories offered in the form
    label_sources: full names of repositories labels may be copied from
    options: result of get_form_options()

    Returns (spec, None) or (None, error_message).
    """
    if owner_type != 'Organization' and owner != user_login:
        return None, (f"You're signed in as {user_login}, but RepoMaster is managing {owner}'s account. "
                      f"Only {owner} can create repositories there.")

    name = (form.get('name') or '').strip()
    if not NAME_PATTERN.match(name) or name in ('.', '..'):
        return None, "Repository names use letters, numbers, '.', '-' and '_' (up to 100 characters)."

    description = ' '.join((form.get('description') or '').split())
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return None, f"The description can be at most {MAX_DESCRIPTION_LENGTH} characters."

    visibility = form.get('visibility')
    if visibility not in ('public', 'private'):
        return None, "Choose public or private."

    spec = {
        'owner': owner, 'owner_type': owner_type, 'name': name, 'description': description,
        'private': visibility == 'private', 'source': form.get('source') or 'blank',
        'template': '', 'include_all_branches': False,
        'auto_init': False, 'gitignore': '', 'license': '',
        'copy_labels_from': '', 'protect_default_branch': bool(form.get('protect_default_branch')),
    }

    if spec['source'] == 'template':
        template = (form.get('template') or '').strip()
        if template not in templates:
            return None, "Choose one of the listed template repositories."
        spec['template'] = template
        spec['include_all_branches'] = bool(form.get('include_all_branches'))
    elif spec['source'] == 'blank':
        gitignore = (form.get('gitignore') or '').strip()
        if gitignore and gitignore not in options['gitignore_templates']:
            return None, f"Unknown .gitignore template '{gitignore}'."
        license_key = (form.get('license') or '').strip()
        if license_key and (not LICENSE_KEY_PATTERN.match(license_key)
                            or license_key not in {l['key'] for l in options['licenses']}):
            return None, f"Unknown license '{license_key}'."
        spec['gitignore'] = gitignore
        spec['license'] = license_key
        # GitHub only applies a .gitignore or license as part of an initial commit
        spec['auto_init'] = bool(form.get('auto_init')) or bool(gitignore) or bool(license_key)
    else:
        return None, "Choose how to start the repository."

    if spec['protect_default_branch'] and spec['source'] == 'blank' and not spec['auto_init']:
        return None, ("Branch protection needs an initial commit. Add a README, .gitignore or license, "
                      "or start from a template.")

    copy_labels_from = (form.get('copy_labels_from') or '').strip()
    if copy_labels_from:
        if copy_labels_from not in label_sources:
            return None, "Choose one of the listed repositories to copy labels from."
        spec['copy_labels_from'] = copy_labels_from

    return spec, None


def _create(spec, user_token):
    """Create the repository itself. Returns (repository, None) or (None, error)."""
    if spec['source'] == 'template':
        payload = {'owner': spec['owner'], 'name': spec['name'], 'description': spec['description'],
                   'private': spec['private'], 'include_all_branches': spec['include_all_branches']}
        return github_api('POST', f"/repos/{spec['template']}/generate", user_token, json=payload)

    payload = {'name': spec['name'], 'description': spec['description'],
               'private': spec['private'], 'auto_init': spec['auto_init']}
    if spec['gitignore']:
        payload['gitignore_template'] = spec['gitignore']
    if spec['license']:
        payload['license_template'] = spec['license']
    path = f"/orgs/{spec['owner']}/repos" if spec['owner_type'] == 'Organization' else '/user/repos'
    return github_api('POST', path, user_token, json=payload)


def _copy_labels(source, target, user_token):
    """Copy labels from `source` to `target`, updating ones that already exist. Returns a step."""
    labels, error = github_api('GET', f'/repos/{source}/labels', user_token, params={'per_page': 100})
    if error:
        return {'name': f'Copy labels from {source}', 'ok': False, 'message': error}

    created = updated = 0
    failed = []
    for label in labels:
        payload = {'name': label['name'], 'color': label.get('color', 'ededed'),
                   'description': label.get('description') or ''}
        _, error = github_api('POST', f'/repos/{target}/labels', user_token, json=payload)
        if not error:
            created += 1
            continue
        # Most likely one of GitHub's default labels already exists: update it instead
        _, error = github_api('PATCH', f"/repos/{target}/labels/{quote(label['name'], safe='')}",
                              user_token, json=payload)
        if error:
            failed.append(label['name'])
        else:
            updated += 1

    message = f"{created} created, {updated} updated"
    if failed:
        message += f", failed: {', '.join(failed)}"
    return {'name': f'Copy labels from {source}', 'ok': not failed, 'message': message}


def _protect_branch(full_name, branch, user_token, sleep=time.sleep):
    """Protect the default branch, retrying while a template-generated repo is still being filled."""
    error = None
    for attempt in range(PROTECTION_ATTEMPTS):
        if attempt:
            sleep(PROTECTION_RETRY_SECONDS)
        _, error = github_api('PUT', f"/repos/{full_name}/branches/{quote(branch, safe='')}/protection",
                              user_token, json=BRANCH_PROTECTION)
        if not error:
            return {'name': f"Protect '{branch}'", 'ok': True,
                    'message': '1 approving review required; force pushes and deletion blocked'}
        if 'not found' not in error.lower():
            break
    return {'name': f"Protect '{branch}'", 'ok': False, 'message': error}


def create_repository(spec, user_token, sleep=time.sleep):
    """
    Create the repository and apply the optional setup steps.
    Returns {'ok', 'repo': {'full_name', 'html_url', 'default_branch'} or None, 'steps': [...]}.
    Setup steps run even if an earlier setup step fails; nothing runs if creation fails.
    """
    action = f"Generate from {spec['template']}" if spec['source'] == 'template' else 'Create repository'
    repository, error = _create(spec, user_token)
    if error:
        logging.error(f"Creating repository {spec['owner']}/{spec['name']} failed: {error}")
        return {'ok': False, 'repo': None, 'steps': [{'name': action, 'ok': False, 'message': error}]}

    repo = {'full_name': repository['full_name'], 'html_url': repository['html_url'],
            'default_branch': repository.get('default_branch') or 'main'}
    steps = [{'name': action, 'ok': True, 'message': repo['full_name']}]

    if spec['copy_labels_from']:
        steps.append(_copy_labels(spec['copy_labels_from'], repo['full_name'], user_token))
    if spec['protect_default_branch']:
        steps.append(_protect_branch(repo['full_name'], repo['default_branch'], user_token, sleep))

    logging.info(f"Created repository {repo['full_name']} with {len(steps) - 1} setup step(s).")
    return {'ok': all(step['ok'] for step in steps), 'repo': repo, 'steps': steps}
