"""branch_management_controller.py

Branch protection editor and branch comparison (issue #41).
All GitHub calls go through repo_controller.github_api, which returns
(json_or_None, error_message) instead of raising.
"""
import re
from urllib.parse import quote
from app.controllers.bulk_controller import BRANCH_PATTERN
from app.controllers.repo_controller import github_api

NAME_PATTERN = re.compile(r'^[A-Za-z0-9._-]{1,100}$')
MAX_APPROVALS = 6
MAX_STATUS_CHECKS = 50
MAX_CHECK_NAME_LENGTH = 255
NOT_PROTECTED = 'Branch not protected'

# Checkboxes on the protection form
TOGGLES = (
    'require_pull_request', 'dismiss_stale_reviews', 'require_code_owner_reviews', 'require_last_push_approval',
    'require_status_checks', 'strict_status_checks', 'enforce_admins', 'required_linear_history',
    'required_conversation_resolution', 'allow_force_pushes', 'allow_deletions',
)


def valid_names(owner, repo):
    """Owner and repository names safe to put in an API path."""
    return all(NAME_PATTERN.match(name or '') and name not in ('.', '..') for name in (owner, repo))


def valid_branch(name):
    """A plausible Git branch name (also rules out path tricks like '..')."""
    return bool(name) and len(name) <= 255 and bool(BRANCH_PATTERN.match(name)) and not name.endswith('.lock')


def _repo_path(owner, repo):
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


def _protection_path(owner, repo, branch):
    return f'{_repo_path(owner, repo)}/branches/{quote(branch, safe="")}/protection'


# --- Protection --------------------------------------------------------------

def get_protection(owner, repo, branch, access_token):
    """
    The branch's protection settings, or None when the branch isn't protected.
    Returns (protection_or_None, error).
    """
    protection, error = github_api('GET', _protection_path(owner, repo, branch), access_token)
    if error == NOT_PROTECTED:
        return None, None
    return protection, error


def _enabled(protection, key):
    return bool(((protection or {}).get(key) or {}).get('enabled'))


def protection_to_form(protection):
    """Current settings as form values (all off for an unprotected branch)."""
    protection = protection or {}
    reviews = protection.get('required_pull_request_reviews')
    checks = protection.get('required_status_checks')
    contexts = [c.get('context') for c in (checks or {}).get('checks') or [] if c.get('context')] \
        or list((checks or {}).get('contexts') or [])
    return {
        'protected': bool(protection),
        'require_pull_request': reviews is not None,
        'required_approvals': (reviews or {}).get('required_approving_review_count', 1) if reviews else 1,
        'dismiss_stale_reviews': bool((reviews or {}).get('dismiss_stale_reviews')),
        'require_code_owner_reviews': bool((reviews or {}).get('require_code_owner_reviews')),
        'require_last_push_approval': bool((reviews or {}).get('require_last_push_approval')),
        'require_status_checks': checks is not None,
        'strict_status_checks': bool((checks or {}).get('strict')),
        'status_checks': '\n'.join(contexts),
        'enforce_admins': _enabled(protection, 'enforce_admins'),
        'required_linear_history': _enabled(protection, 'required_linear_history'),
        'required_conversation_resolution': _enabled(protection, 'required_conversation_resolution'),
        'allow_force_pushes': _enabled(protection, 'allow_force_pushes'),
        'allow_deletions': _enabled(protection, 'allow_deletions'),
        'has_restrictions': protection.get('restrictions') is not None,
    }


def _logins(entries, key):
    return [entry[key] for entry in entries or [] if entry.get(key)]


def _who(allowances):
    """Convert GitHub's users/teams/apps objects back into the names PUT expects."""
    allowances = allowances or {}
    return {'users': _logins(allowances.get('users'), 'login'),
            'teams': _logins(allowances.get('teams'), 'slug'),
            'apps': _logins(allowances.get('apps'), 'slug')}


def parse_status_checks(raw):
    """Status check names, one per line. Returns (names, error)."""
    names = []
    for line in (raw or '').splitlines():
        name = line.strip()
        if not name or name in names:
            continue
        if len(name) > MAX_CHECK_NAME_LENGTH or any(ord(ch) < 32 for ch in name):
            return None, f"'{name[:40]}' isn't a valid status check name."
        names.append(name)
    if len(names) > MAX_STATUS_CHECKS:
        return None, f"At most {MAX_STATUS_CHECKS} status checks can be required."
    return names, None


def build_protection_payload(form, existing=None):
    """
    The body for PUT .../protection from the editor form. Settings the editor doesn't show
    (push restrictions, review dismissal / bypass lists, the app each check must come from)
    are kept from `existing` so saving never silently drops them.
    Returns (payload, error).
    """
    on = {name: form.get(name) == 'on' for name in TOGGLES}
    existing = existing or {}

    reviews = None
    if on['require_pull_request']:
        try:
            approvals = int(form.get('required_approvals', 1))
        except (TypeError, ValueError):
            return None, "Required approvals must be a number."
        if not 0 <= approvals <= MAX_APPROVALS:
            return None, f"Required approvals must be between 0 and {MAX_APPROVALS}."
        reviews = {
            'required_approving_review_count': approvals,
            'dismiss_stale_reviews': on['dismiss_stale_reviews'],
            'require_code_owner_reviews': on['require_code_owner_reviews'],
            'require_last_push_approval': on['require_last_push_approval'],
        }
        old_reviews = existing.get('required_pull_request_reviews') or {}
        if old_reviews.get('dismissal_restrictions'):
            reviews['dismissal_restrictions'] = _who(old_reviews['dismissal_restrictions'])
        if old_reviews.get('bypass_pull_request_allowances'):
            reviews['bypass_pull_request_allowances'] = _who(old_reviews['bypass_pull_request_allowances'])

    checks = None
    if on['require_status_checks']:
        names, error = parse_status_checks(form.get('status_checks'))
        if error:
            return None, error
        old_apps = {c.get('context'): c.get('app_id')
                    for c in (existing.get('required_status_checks') or {}).get('checks') or []}
        checks = {'strict': on['strict_status_checks'], 'checks': [
            {'context': name, **({'app_id': old_apps[name]} if old_apps.get(name) is not None else {})}
            for name in names
        ]}

    restrictions = existing.get('restrictions')
    payload = {
        'required_status_checks': checks,
        'enforce_admins': on['enforce_admins'],
        'required_pull_request_reviews': reviews,
        'restrictions': _who(restrictions) if restrictions is not None else None,
        'required_linear_history': on['required_linear_history'],
        'required_conversation_resolution': on['required_conversation_resolution'],
        'allow_force_pushes': on['allow_force_pushes'],
        'allow_deletions': on['allow_deletions'],
    }
    return payload, None


def save_protection(owner, repo, branch, access_token, payload):
    """Create or replace the branch's protection. Returns (protection, error)."""
    return github_api('PUT', _protection_path(owner, repo, branch), access_token, json=payload)


def remove_protection(owner, repo, branch, access_token):
    """Remove all protection from the branch. Returns (True, None) or (False, error)."""
    _, error = github_api('DELETE', _protection_path(owner, repo, branch), access_token)
    return error is None, error


# --- Comparison --------------------------------------------------------------

def compare_branches(owner, repo, base, head, access_token):
    """
    Compare two branches. Returns (comparison, error) where comparison has
    status (ahead / behind / identical / diverged), ahead_by, behind_by,
    total_commits, commits (up to 250, oldest first) and files.
    """
    path = f'{_repo_path(owner, repo)}/compare/{quote(base, safe="/")}...{quote(head, safe="/")}'
    return github_api('GET', path, access_token)


def find_open_pull_request(owner, repo, base, head, access_token):
    """An open pull request from head into base, if there is one (errors are ignored)."""
    pulls, error = github_api('GET', f'{_repo_path(owner, repo)}/pulls', access_token,
                              params={'state': 'open', 'base': base, 'head': f'{owner}:{head}', 'per_page': 1})
    return pulls[0] if not error and pulls else None


def describe_comparison(comparison, base, head):
    """One sentence explaining how head relates to base."""
    ahead, behind = comparison.get('ahead_by', 0), comparison.get('behind_by', 0)
    status = comparison.get('status')
    if status == 'identical':
        return f"{head} and {base} are identical."
    if status == 'ahead':
        return f"{head} is {ahead} commit{'s' if ahead != 1 else ''} ahead of {base}."
    if status == 'behind':
        return f"{head} is {behind} commit{'s' if behind != 1 else ''} behind {base}."
    return (f"{head} and {base} have diverged: {head} is {ahead} commit{'s' if ahead != 1 else ''} ahead "
            f"and {behind} behind.")


def commit_rows(commits):
    """Commits for display: short sha, first line of the message, author and date."""
    rows = []
    for commit in commits or []:
        details = commit.get('commit') or {}
        author = details.get('author') or {}
        rows.append({
            'sha': (commit.get('sha') or '')[:7],
            'html_url': commit.get('html_url'),
            'message': (details.get('message') or '').split('\n', 1)[0],
            'author': (commit.get('author') or {}).get('login') or author.get('name') or 'unknown',
            'date': author.get('date'),
        })
    return rows
