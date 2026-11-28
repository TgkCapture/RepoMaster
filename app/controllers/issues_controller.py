"""issues_controller.py

Listing, creating and closing issues, plus full issue management (issue #39):
detail, edit, close/reopen, comments, labels, assignees and milestones.
"""
import logging
import re
from urllib.parse import quote
from app import github_http
from flask import session
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token
from app.controllers.repo_controller import github_api

STATES = ('open', 'closed', 'all')
CLOSE_REASONS = {'completed': 'Completed', 'not_planned': 'Not planned'}
MAX_TITLE_LENGTH = 256
MAX_BODY_LENGTH = 65536
MAX_LABEL_LENGTH = 50
LOGIN_PATTERN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$')
SUCCESS_MESSAGES = {
    'edit': "Issue updated.",
    'close': "Issue closed.",
    'reopen': "Issue reopened.",
    'comment': "Comment posted.",
    'add_label': "Label added.",
    'remove_label': "Label removed.",
    'add_assignee': "Assignee added.",
    'remove_assignee': "Assignee removed.",
    'set_milestone': "Milestone updated.",
}
ACTIONS = tuple(SUCCESS_MESSAGES)

def get_github_issues(repo_name):
    """Fetches GitHub issues within a repository."""
    
    username = session.get('github_username') 
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch GitHub issues.")
        return None

    url = f'https://api.github.com/repos/{username}/{repo_name}/issues'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = github_http.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        issues = response.json()
        logging.info(f"Fetched {len(issues)} issues for repository {repo_name}.")
        return issues
    except RequestException as e:
        logging.error(f"Failed to fetch issues for repository {repo_name}: {e}")
        return None

def create_github_issue(repo_name, title, body=None):
    """Creates a new GitHub issue."""
    username = session.get('github_username')  
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot create GitHub issues.")
        return None

    url = f'https://api.github.com/repos/{username}/{repo_name}/issues'
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {"title": title, "body": body}

    try:
        response = github_http.post(url, json=data, headers=headers, timeout=60)
        response.raise_for_status()
        issue = response.json()
        logging.info(f"Issue created successfully in repository {repo_name}.")
        return issue
    except RequestException as e:
        logging.error(f"Failed to create issue in repository {repo_name}: {e}")
        return None

def close_github_issue(repo_name, issue_number):
    """Closes an existing GitHub issue."""
    username = session.get('github_username')
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot close GitHub issues.")
        return None

    url = f'https://api.github.com/repos/{username}/{repo_name}/issues/{issue_number}'
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {"state": "closed"}

    try:
        response = github_http.patch(url, json=data, headers=headers, timeout=60)
        response.raise_for_status()
        closed_issue = response.json()
        logging.info(f"Issue #{issue_number} successfully closed in repository {repo_name}.")
        return closed_issue
    except RequestException as e:
        logging.error(f"Failed to close issue #{issue_number} in repository {repo_name}: {e}")
        return None


# --- Issue management (issue #39) --------------------------------------------
# These go through repo_controller.github_api, which returns
# (json_or_None, error_message) instead of raising.

def parse_state(value):
    """The issue list's state filter: 'open' (default), 'closed' or 'all'."""
    return value if value in STATES else 'open'


def parse_issue_number(value):
    """A positive number as an int, or None."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _repo_path(owner, repo):
    return f'/repos/{quote(owner or "", safe="")}/{quote(repo, safe="")}'


def _issue_path(owner, repo, number):
    return f'{_repo_path(owner, repo)}/issues/{number}'


def list_issues(owner, repo, access_token, state='open'):
    """Issues in a repository, pull requests left out. Returns (issues, error)."""
    issues, error = github_api('GET', f'{_repo_path(owner, repo)}/issues', access_token,
                               params={'state': parse_state(state), 'per_page': 100})
    if error:
        return None, error
    return [issue for issue in issues if 'pull_request' not in issue], None


def get_issue(owner, repo, number, access_token):
    """One issue (or pull request). Returns (issue, error)."""
    return github_api('GET', _issue_path(owner, repo, number), access_token)


def list_issue_comments(owner, repo, number, access_token):
    """The issue's comments, oldest first. Returns (comments, error)."""
    return github_api('GET', f'{_issue_path(owner, repo, number)}/comments', access_token,
                      params={'per_page': 100})


def get_issue_options(owner, repo, access_token):
    """
    The labels, assignable users and open milestones of a repository, for the
    issue page's pickers. A list that can't be fetched comes back empty.
    """
    base = _repo_path(owner, repo)
    options = {}
    for key, path, params in (
        ('labels', f'{base}/labels', {'per_page': 100}),
        ('assignees', f'{base}/assignees', {'per_page': 100}),
        ('milestones', f'{base}/milestones', {'state': 'open', 'per_page': 100}),
    ):
        data, error = github_api('GET', path, access_token, params=params)
        if error:
            logging.warning(f"Could not fetch {key} for {owner}/{repo}: {error}")
        options[key] = data or []
    return options


def update_issue(owner, repo, number, access_token, fields):
    """PATCH an issue (title, body, state, state_reason, milestone...). Returns (issue, error)."""
    return github_api('PATCH', _issue_path(owner, repo, number), access_token, json=fields)


def _text(form, name):
    return (form.get(name) or '').strip()


def validate_issue_action(action, form, options=None):
    """
    Check a form submitted from the issue page.
    Returns ((method, path_suffix, payload), None) or (None, error_message).
    `path_suffix` is appended to /repos/{owner}/{repo}/issues/{number}; payload None means no body.
    `options` (from get_issue_options) limits milestones to the repository's open ones when given.
    """
    if action not in ACTIONS:
        return None, "Unknown action."

    if action == 'edit':
        title, body = _text(form, 'title'), form.get('body') or ''
        if not title:
            return None, "The title can't be empty."
        if len(title) > MAX_TITLE_LENGTH:
            return None, f"The title can be at most {MAX_TITLE_LENGTH} characters."
        if len(body) > MAX_BODY_LENGTH:
            return None, f"The description can be at most {MAX_BODY_LENGTH} characters."
        return ('PATCH', '', {'title': title, 'body': body}), None

    if action == 'close':
        reason = form.get('state_reason') or 'completed'
        if reason not in CLOSE_REASONS:
            return None, "Unknown close reason."
        return ('PATCH', '', {'state': 'closed', 'state_reason': reason}), None

    if action == 'reopen':
        return ('PATCH', '', {'state': 'open'}), None

    if action == 'comment':
        body = form.get('body') or ''
        if not body.strip():
            return None, "The comment can't be empty."
        if len(body) > MAX_BODY_LENGTH:
            return None, f"The comment can be at most {MAX_BODY_LENGTH} characters."
        return ('POST', '/comments', {'body': body}), None

    if action in ('add_label', 'remove_label'):
        label = _text(form, 'label')
        if not label or len(label) > MAX_LABEL_LENGTH:
            return None, "Choose a label."
        if action == 'add_label':
            return ('POST', '/labels', {'labels': [label]}), None
        return ('DELETE', f'/labels/{quote(label, safe="")}', None), None

    if action in ('add_assignee', 'remove_assignee'):
        login = _text(form, 'assignee').lstrip('@')
        if not LOGIN_PATTERN.match(login):
            return None, "Choose a valid GitHub username."
        method = 'POST' if action == 'add_assignee' else 'DELETE'
        return (method, '/assignees', {'assignees': [login]}), None

    # set_milestone: an empty value clears it
    value = _text(form, 'milestone')
    if not value:
        return ('PATCH', '', {'milestone': None}), None
    milestone = parse_issue_number(value)
    if milestone is None:
        return None, "Choose a milestone."
    if options is not None and milestone not in {m.get('number') for m in options.get('milestones', [])}:
        return None, "That milestone doesn't exist or is closed."
    return ('PATCH', '', {'milestone': milestone}), None


def apply_issue_action(owner, repo, number, access_token, action, form, options=None):
    """Validate and perform one action on an issue. Returns (success_message, error)."""
    request_spec, error = validate_issue_action(action, form, options)
    if error:
        return None, error
    method, suffix, payload = request_spec
    kwargs = {'json': payload} if payload is not None else {}
    result, error = github_api(method, f'{_issue_path(owner, repo, number)}{suffix}', access_token, **kwargs)
    if error:
        return None, error
    if action == 'add_assignee':
        # GitHub silently skips users who can't be assigned; the response shows who actually is.
        login = payload['assignees'][0]
        assigned = {a.get('login', '').lower() for a in (result or {}).get('assignees') or []}
        if login.lower() not in assigned:
            return None, f"{login} can't be assigned to issues in this repository."
    return SUCCESS_MESSAGES[action], None