"""bulk_controller.py

Validate and apply one action to many repositories at once (issue #35). The action runs
as a background job with progress reporting (issue #54).
"""
import re
import logging
import time
from app import github_http
from app.controllers.auth_controller import get_installation_access_token
from app.controllers.jobs_controller import finish_job, save_progress
from app.controllers.repo_controller import (
    update_repository, get_repository_topics, replace_repository_topics,
)
from app.controllers.soft_delete_controller import schedule_deletion
from app.controllers.audit_controller import record_audit
from app.controllers.collaborators_controller import LOGIN_PATTERN, ROLES, add_collaborator, remove_access, role_label

# Longest wait for a rate limit to clear before retrying a repository. Longer limits
# stop the job; the remaining repositories are reported as skipped.
MAX_RATE_LIMIT_WAIT = 90  # seconds

# Text the user must type on the confirmation page before a bulk delete is applied
DELETE_CONFIRMATION_TEXT = 'delete'

# action -> label shown in the UI, which extra input it needs, and the past-tense result
ACTIONS = {
    'archive': {'label': 'Archive (make read-only)', 'needs': None, 'done': 'Archived'},
    'unarchive': {'label': 'Unarchive', 'needs': None, 'done': 'Unarchived'},
    'make_private': {'label': 'Make private', 'needs': None, 'done': 'Made private'},
    'make_public': {'label': 'Make public', 'needs': None, 'done': 'Made public'},
    'add_topics': {'label': 'Add topics', 'needs': 'topics', 'done': 'Topics updated'},
    'remove_topics': {'label': 'Remove topics', 'needs': 'topics', 'done': 'Topics updated'},
    'set_default_branch': {'label': 'Change default branch', 'needs': 'branch', 'done': 'Default branch changed'},
    'add_collaborator': {'label': 'Add a collaborator', 'needs': 'collaborator', 'done': 'Access granted'},
    'remove_collaborator': {'label': 'Remove a collaborator', 'needs': 'login', 'done': 'Removed'},
    'delete': {'label': 'Delete (archived first, restorable for a few days)', 'needs': None, 'done': 'Deleted'},
}

# Fields sent to PATCH /repos/{owner}/{repo} for the simple actions
REPOSITORY_FIELDS = {
    'archive': {'archived': True},
    'unarchive': {'archived': False},
    'make_private': {'private': True},
    'make_public': {'private': False},
}

MAX_TOPICS_PER_REPO = 20  # GitHub's limit
TOPIC_PATTERN = re.compile(r'^[a-z0-9][a-z0-9-]{0,49}$')
REPO_FULL_NAME_PATTERN = re.compile(r'^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$')
# Simplified git ref-name rules: no whitespace or ~^:?*[\ , no "..", "//" or "@{",
# and it must not start or end with "/" or "." or end with ".lock"
# bulk action -> audit log action
AUDIT_ACTION = {
    'archive': 'repository.archive', 'unarchive': 'repository.unarchive',
    'make_private': 'repository.make_private', 'make_public': 'repository.make_public',
    'add_topics': 'repository.add_topics', 'remove_topics': 'repository.remove_topics',
    'set_default_branch': 'repository.set_default_branch',
    'add_collaborator': 'collaborator.invite', 'remove_collaborator': 'collaborator.remove',
}

BRANCH_PATTERN = re.compile(r'^(?![/.])(?!.*(?:\.\.|//|@\{))[^\s~^:?*\[\\]+(?<![/.])$')


def parse_topics(raw):
    """
    Split a comma/space separated list into normalised GitHub topics.
    Returns (topics, None) or (None, error_message).
    """
    topics = []
    for topic in re.split(r'[\s,]+', (raw or '').strip().lower()):
        if topic and topic not in topics:
            topics.append(topic)

    if not topics:
        return None, "Enter at least one topic."
    invalid = [t for t in topics if not TOPIC_PATTERN.match(t)]
    if invalid:
        return None, (f"Invalid topic(s): {', '.join(invalid)}. Topics use lowercase letters, numbers "
                      "and hyphens, start with a letter or number, and are at most 50 characters.")
    if len(topics) > MAX_TOPICS_PER_REPO:
        return None, f"A repository can have at most {MAX_TOPICS_PER_REPO} topics."
    return topics, None


def validate_bulk_request(action, repo_full_names, topics_raw='', branch='', login='', role=''):
    """
    Check a bulk request from the form.
    Returns (bulk_request, None) or (None, error_message), where bulk_request is
    {'action', 'repos', 'topics', 'branch', 'login', 'role'}.
    """
    if action not in ACTIONS:
        return None, "Choose an action."

    repos = []
    for full_name in repo_full_names:
        full_name = (full_name or '').strip()
        if full_name and full_name not in repos:
            repos.append(full_name)
    if not repos:
        return None, "Select at least one repository."
    invalid = [name for name in repos if not REPO_FULL_NAME_PATTERN.match(name)]
    if invalid:
        return None, f"Invalid repository name(s): {', '.join(invalid)}"

    bulk_request = {'action': action, 'repos': repos, 'topics': [], 'branch': '', 'login': '', 'role': ''}

    needs = ACTIONS[action]['needs']
    if needs == 'topics':
        topics, error = parse_topics(topics_raw)
        if error:
            return None, error
        bulk_request['topics'] = topics
    elif needs == 'branch':
        branch = (branch or '').strip()
        if not branch:
            return None, "Enter the branch name to use as the default branch."
        if not BRANCH_PATTERN.match(branch) or branch.endswith('.lock'):
            return None, f"'{branch}' is not a valid branch name."
        bulk_request['branch'] = branch
    elif needs in ('collaborator', 'login'):
        login = (login or '').strip().lstrip('@')
        if not LOGIN_PATTERN.match(login):
            return None, "Enter a valid GitHub username."
        if any(name.split('/', 1)[0].lower() == login.lower() for name in repos):
            return None, "The repository owner's access can't be changed."
        bulk_request['login'] = login
        if needs == 'collaborator':
            if role not in ROLES:
                return None, "Choose a permission level."
            bulk_request['role'] = role

    return bulk_request, None


def is_delete_confirmed(bulk_request, confirmation_text):
    """True unless this is a delete that the user has not confirmed by typing the confirmation text."""
    if bulk_request['action'] != 'delete':
        return True
    return (confirmation_text or '').strip().lower() == DELETE_CONFIRMATION_TEXT


def describe_bulk_request(bulk_request):
    """One-line, human readable summary of what will happen to each repository."""
    action = bulk_request['action']
    if action == 'add_topics':
        return f"Add topics: {', '.join(bulk_request['topics'])}"
    if action == 'remove_topics':
        return f"Remove topics: {', '.join(bulk_request['topics'])}"
    if action == 'set_default_branch':
        return f"Change the default branch to '{bulk_request['branch']}'"
    if action == 'add_collaborator':
        return (f"Give {bulk_request['login']} {role_label(bulk_request['role'])} access "
                "(invites them where they aren't a collaborator yet)")
    if action == 'remove_collaborator':
        return f"Remove {bulk_request['login']}'s access (and cancel pending invitations)"
    return ACTIONS[action]['label']


def _apply_topics(owner, repo, access_token, action, topics):
    current, error = get_repository_topics(owner, repo, access_token)
    if error:
        return False, error

    if action == 'add_topics':
        updated = current + [t for t in topics if t not in current]
    else:
        updated = [t for t in current if t not in topics]

    if updated == current:
        return True, "No change needed"
    if len(updated) > MAX_TOPICS_PER_REPO:
        return False, f"Would exceed GitHub's limit of {MAX_TOPICS_PER_REPO} topics ({len(updated)})"

    result, error = replace_repository_topics(owner, repo, access_token, updated)
    if error:
        return False, error
    return True, f"Topics: {', '.join(result) or 'none'}"


def _apply_one(full_name, access_token, bulk_request, installation_id, actor):
    owner, repo = full_name.split('/', 1)
    action = bulk_request['action']
    if action in ('add_topics', 'remove_topics'):
        return _apply_topics(owner, repo, access_token, action, bulk_request['topics'])
    if action == 'add_collaborator':
        message, error = add_collaborator(owner, repo, bulk_request['login'], bulk_request['role'], access_token)
        return (error is None), (error or message)
    if action == 'remove_collaborator':
        return remove_access(owner, repo, bulk_request['login'], access_token)
    if action == 'delete':
        return schedule_deletion(owner, repo, access_token, installation_id=installation_id, actor=actor)
    fields = (REPOSITORY_FIELDS[action] if action in REPOSITORY_FIELDS
              else {'default_branch': bulk_request['branch']})
    _, error = update_repository(owner, repo, access_token, fields)
    return (error is None), (error or ACTIONS[action]['done'])


def apply_bulk_action(access_token, bulk_request, installation_id=None, actor=None, on_progress=None,
                      sleep=time.sleep):
    """
    Apply the action to every repository, continuing past failures.
    Returns a list of {'repo', 'ok', 'message'} in the order the repositories were given.

    access_token may be a function returning a token, so long jobs pick up a fresh one.
    on_progress(result) is called after each repository. When GitHub's rate limit refuses
    a repository, it waits (up to MAX_RATE_LIMIT_WAIT) and retries once; every bulk action
    is safe to repeat. A longer limit stops the job and the rest are reported as skipped.
    """
    action = bulk_request['action']
    results = []
    stopped = None

    def token():
        return access_token() if callable(access_token) else access_token

    for full_name in bulk_request['repos']:
        skipped = bool(stopped)
        if skipped:
            ok, message = False, f"Skipped: {stopped}"
        else:
            github_http.pop_rate_limited()
            ok, message = _apply_one(full_name, token(), bulk_request, installation_id, actor)
            delay = github_http.pop_rate_limited()
            if not ok and delay is not None:
                if delay <= MAX_RATE_LIMIT_WAIT:
                    logging.info(f"Bulk '{action}': rate limited on {full_name}, retrying in {delay}s.")
                    sleep(delay)
                    ok, message = _apply_one(full_name, token(), bulk_request, installation_id, actor)
                    github_http.pop_rate_limited()
                else:
                    stopped = message

        result = {'repo': full_name, 'ok': ok, 'message': message}
        results.append(result)
        if action in AUDIT_ACTION and not skipped:
            target = (bulk_request['login'] or bulk_request['branch'] or ', '.join(bulk_request['topics'])) or None
            record_audit(AUDIT_ACTION[action], full_name, ok, message, target=target,
                         installation_id=installation_id, actor=actor)
        if on_progress:
            on_progress(result)

    succeeded = sum(1 for r in results if r['ok'])
    logging.info(f"Bulk action '{action}': {succeeded}/{len(results)} repositories succeeded.")
    return results


def run_bulk_job(job_id, bulk_request, installation_id, actor):
    """The background job behind a bulk action: apply it, saving progress after each repository."""
    results = []

    def progress(result):
        results.append(result)
        save_progress(job_id, results)

    apply_bulk_action(lambda: get_installation_access_token(installation_id), bulk_request,
                      installation_id=installation_id, actor=actor, on_progress=progress)
    finish_job(job_id, results)
