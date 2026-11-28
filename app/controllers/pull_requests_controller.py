"""pull_requests_controller.py

Listing and creating pull requests, plus review and merge support (issue #40):
changed files and diffs, reviews, review comments, check runs, merge methods,
deleting the head branch after merging, and close / reopen.
"""
import logging
from urllib.parse import quote
import requests
from app import github_http
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token
from app.controllers.repo_controller import delete_branch_ref, github_api

STATES = ('open', 'closed', 'all')
MERGE_METHODS = {
    'merge': 'Create a merge commit',
    'squash': 'Squash and merge',
    'rebase': 'Rebase and merge',
}
# Repository settings that turn each merge method on or off
MERGE_METHOD_SETTINGS = {'merge': 'allow_merge_commit', 'squash': 'allow_squash_merge', 'rebase': 'allow_rebase_merge'}
MAX_COMMIT_TITLE_LENGTH = 256
MAX_COMMIT_MESSAGE_LENGTH = 65536
MAX_FILES = 100
SUCCESS_MESSAGES = {'merge': "Pull request merged.", 'close': "Pull request closed.", 'reopen': "Pull request reopened."}
ACTIONS = tuple(SUCCESS_MESSAGES)


def get_pull_requests(owner, repo_name):
    """Lists all pull requests for a repository."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch pull requests.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = github_http.get(api_url, headers=headers, timeout=60)
        response.raise_for_status()

        pulls = response.json()
        logging.info(f"Fetched {len(pulls)} pull requests for repository {repo_name}.")
        return pulls
    except RequestException as e:
        logging.error(f"Failed to fetch pull requests for repository {repo_name}: {e}")
        return None

def create_pull_request(owner, repo_name, title, body, base, head):
    """Creates a new GitHub pull request."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot create pull request.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    payload = {'title': title, 'body': body, 'base': base, 'head': head}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    logging.debug(f"Payload for creating PR: {payload}")

    try:
        response = github_http.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        pull = response.json()
        logging.info(f"Pull request created successfully in repository {repo_name}.")
        return pull
    except requests.exceptions.RequestException as e:
        # A failed Response is falsy, so compare against None explicitly
        if e.response is not None:
            logging.error(f"Failed to create pull request: {e.response.text}")
        else:
            logging.error(f"Failed to create pull request: {e}")
        return None


# --- Review and merge (issue #40) --------------------------------------------
# These go through repo_controller.github_api, which returns
# (json_or_None, error_message) instead of raising.

def parse_state(value):
    """The list's state filter: 'open' (default), 'closed' or 'all'."""
    return value if value in STATES else 'open'


def _repo_path(owner, repo):
    return f'/repos/{quote(owner or "", safe="")}/{quote(repo, safe="")}'


def _pull_path(owner, repo, number):
    return f'{_repo_path(owner, repo)}/pulls/{number}'


def list_pull_requests(owner, repo, access_token, state='open'):
    """Pull requests in a repository, most recently updated first. Returns (pulls, error)."""
    return github_api('GET', f'{_repo_path(owner, repo)}/pulls', access_token,
                      params={'state': parse_state(state), 'sort': 'updated', 'direction': 'desc', 'per_page': 100})


def get_pull_request(owner, repo, number, access_token):
    """One pull request, including its mergeable state. Returns (pull, error)."""
    return github_api('GET', _pull_path(owner, repo, number), access_token)


def get_review_data(owner, repo, pull, access_token):
    """
    Changed files, reviews, review comments and check runs for a pull request.
    Each part that can't be fetched comes back empty, with its error in `errors`.
    """
    number = pull['number']
    base = _pull_path(owner, repo, number)
    data, errors = {}, {}
    for key, path in (('files', f'{base}/files'), ('reviews', f'{base}/reviews'),
                      ('review_comments', f'{base}/comments')):
        result, error = github_api('GET', path, access_token, params={'per_page': MAX_FILES})
        data[key] = result or []
        if error:
            errors[key] = error

    head_sha = (pull.get('head') or {}).get('sha')
    data['check_runs'] = []
    if head_sha:
        result, error = github_api('GET', f'{_repo_path(owner, repo)}/commits/{quote(head_sha, safe="")}/check-runs',
                                   access_token, params={'per_page': 100})
        data['check_runs'] = (result or {}).get('check_runs', [])
        if error:
            errors['check_runs'] = error
    data['errors'] = errors
    return data


def diff_lines(patch):
    """Split a unified diff into (css_class, text) pairs for display."""
    lines = []
    for line in (patch or '').splitlines():
        if line.startswith('@@'):
            css = 'hunk'
        elif line.startswith('+'):
            css = 'add'
        elif line.startswith('-'):
            css = 'del'
        else:
            css = ''
        lines.append((css, line))
    return lines


def summarize_checks(check_runs):
    """
    Overall CI state from check runs: 'none', 'pending', 'failure' or 'success',
    plus how many runs are in each group.
    """
    counts = {'success': 0, 'failure': 0, 'pending': 0, 'skipped': 0}
    for run in check_runs:
        if run.get('status') != 'completed':
            counts['pending'] += 1
        elif run.get('conclusion') in ('success', 'neutral'):
            counts['success'] += 1
        elif run.get('conclusion') == 'skipped':
            counts['skipped'] += 1
        else:  # failure, cancelled, timed_out, action_required, stale
            counts['failure'] += 1
    if not check_runs:
        state = 'none'
    elif counts['failure']:
        state = 'failure'
    elif counts['pending']:
        state = 'pending'
    else:
        state = 'success'
    return {'state': state, **counts}


def summarize_reviews(reviews):
    """
    Each reviewer's latest deciding review (APPROVED / CHANGES_REQUESTED / DISMISSED),
    the way GitHub decides whether a pull request is approved. Comment-only reviews don't count.
    """
    latest = {}
    for review in reviews:  # GitHub returns them oldest first
        login = (review.get('user') or {}).get('login')
        if login and review.get('state') in ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED'):
            latest[login] = review['state']
    return {
        'approved': sorted(login for login, state in latest.items() if state == 'APPROVED'),
        'changes_requested': sorted(login for login, state in latest.items() if state == 'CHANGES_REQUESTED'),
    }


def merge_status(pull):
    """
    A (level, message) pair explaining whether the pull request can be merged,
    where level is a Bootstrap alert colour. Based on GitHub's `mergeable` / `mergeable_state`.
    """
    if pull.get('merged'):
        return 'info', "This pull request has been merged."
    if pull.get('state') == 'closed':
        return 'secondary', "This pull request is closed."
    if pull.get('draft'):
        return 'secondary', "This is a draft pull request. Mark it ready for review on GitHub before merging."
    if pull.get('mergeable') is None:
        return 'secondary', "GitHub is still checking whether this pull request can be merged. Reload in a moment."
    state = pull.get('mergeable_state')
    if pull.get('mergeable') is False or state == 'dirty':
        return 'danger', ("This branch has merge conflicts that must be resolved before it can be merged. "
                          "Resolve them on GitHub or locally, then push.")
    if state == 'blocked':
        return 'warning', "Merging is blocked by branch protection (e.g. a required review or check hasn't passed)."
    if state == 'behind':
        return 'warning', "The head branch is behind the base branch. Branch protection may require updating it first."
    if state == 'unstable':
        return 'warning', "Some checks are failing or still running. You can still merge."
    return 'success', "This branch has no conflicts with the base branch."


def allowed_merge_methods(pull):
    """The merge methods the base repository allows (all of them if GitHub didn't say)."""
    repo = (pull.get('base') or {}).get('repo') or {}
    allowed = {key: label for key, label in MERGE_METHODS.items()
               if repo.get(MERGE_METHOD_SETTINGS[key]) is not False}
    return allowed or dict(MERGE_METHODS)


def can_delete_head_branch(pull):
    """
    The head branch can be deleted after merging when it lives in the same repository
    (not a fork) and isn't the repository's default branch.
    """
    head, base = pull.get('head') or {}, pull.get('base') or {}
    head_repo, base_repo = head.get('repo') or {}, base.get('repo') or {}
    return bool(head.get('ref')) and bool(head_repo.get('full_name')) \
        and head_repo.get('full_name') == base_repo.get('full_name') \
        and head.get('ref') != base_repo.get('default_branch')


def validate_pull_request_action(action, form, pull):
    """
    Check a form submitted from the pull request page against the current pull request.
    Returns (spec, None) or (None, error_message).
    """
    if action not in ACTIONS:
        return None, "Unknown action."
    if action == 'reopen':
        if pull.get('merged'):
            return None, "A merged pull request can't be reopened."
        return {'action': 'reopen'}, None
    if pull.get('state') != 'open':
        return None, "This pull request isn't open."
    if action == 'close':
        return {'action': 'close'}, None

    method = form.get('merge_method') or 'merge'
    if method not in allowed_merge_methods(pull):
        return None, "That merge method isn't allowed in this repository."
    expected_sha = (form.get('sha') or '').strip()
    if not expected_sha:
        return None, "The page is out of date. Reload it and try again."
    title = (form.get('commit_title') or '').strip()
    message = form.get('commit_message') or ''
    if len(title) > MAX_COMMIT_TITLE_LENGTH:
        return None, f"The commit title can be at most {MAX_COMMIT_TITLE_LENGTH} characters."
    if len(message) > MAX_COMMIT_MESSAGE_LENGTH:
        return None, f"The commit message can be at most {MAX_COMMIT_MESSAGE_LENGTH} characters."

    payload = {'merge_method': method, 'sha': expected_sha}
    if method != 'rebase':  # rebase merges keep the original commits
        if title:
            payload['commit_title'] = title
        if message.strip():
            payload['commit_message'] = message
    delete_branch = form.get('delete_branch') == 'on' and can_delete_head_branch(pull)
    return {'action': 'merge', 'payload': payload, 'delete_branch': delete_branch}, None


def apply_pull_request_action(owner, repo, number, access_token, action, form):
    """
    Validate and perform merge / close / reopen. Returns (messages, error) where
    messages is a list of (category, text) to show; error is set when nothing happened.
    """
    pull, error = get_pull_request(owner, repo, number, access_token)
    if error:
        return None, error
    spec, error = validate_pull_request_action(action, form, pull)
    if error:
        return None, error

    if action in ('close', 'reopen'):
        state = 'closed' if action == 'close' else 'open'
        _, error = github_api('PATCH', _pull_path(owner, repo, number), access_token, json={'state': state})
        return (None, error) if error else ([('success', SUCCESS_MESSAGES[action])], None)

    _, error = github_api('PUT', f'{_pull_path(owner, repo, number)}/merge', access_token, json=spec['payload'])
    if error:
        # 405: not mergeable (e.g. conflicts or branch protection), 409: head changed since the page loaded
        if error.lower().startswith('head branch was modified'):
            error = "New commits were pushed since you loaded this page. Review them and try again."
        return None, f"Could not merge: {error}"

    messages = [('success', SUCCESS_MESSAGES['merge'])]
    if spec['delete_branch']:
        branch = pull['head']['ref']
        deleted, error = delete_branch_ref(owner, repo, branch, access_token)
        if deleted:
            messages.append(('success', f"Branch {branch} deleted."))
        else:
            messages.append(('error', f"Merged, but the branch {branch} couldn't be deleted: {error}"))
    return messages, None
