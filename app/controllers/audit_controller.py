"""audit_controller.py

Audit log (issue #51): every destructive or access-changing action RepoMaster takes is
recorded with who did it, on which installation and repository, and whether it worked.

Recording never breaks the action it describes: the change has already happened on
GitHub, so a database problem is logged instead of raised.
"""
import logging
import re
from flask import has_request_context, session
from app.db import get_db
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago

PER_PAGE = 50
SYSTEM_ACTOR = 'RepoMaster (scheduled)'

# action key -> label. Every recorded action must be listed here.
AUDIT_ACTIONS = {
    'repository.delete_scheduled': 'Repository deletion scheduled',
    'repository.delete_cancelled': 'Repository deletion undone',
    'repository.deleted': 'Repository deleted',
    'repository.delete_kept': 'Scheduled deletion skipped',
    'repository.archive': 'Repository archived',
    'repository.unarchive': 'Repository unarchived',
    'repository.make_private': 'Repository made private',
    'repository.make_public': 'Repository made public',
    'repository.add_topics': 'Topics added',
    'repository.remove_topics': 'Topics removed',
    'repository.set_default_branch': 'Default branch changed',
    'branch.delete': 'Branch deleted',
    'branch.rename': 'Branch renamed',
    'branch.protection_update': 'Branch protection changed',
    'branch.protection_remove': 'Branch protection removed',
    'file.delete': 'File deleted',
    'release.delete': 'Release deleted',
    'release.asset_delete': 'Release file deleted',
    'secret.set': 'Secret saved',
    'secret.delete': 'Secret deleted',
    'collaborator.invite': 'Collaborator invited',
    'collaborator.set_role': 'Collaborator permission changed',
    'collaborator.remove': 'Collaborator removed',
    'collaborator.invitation_role': 'Invitation permission changed',
    'collaborator.cancel_invitation': 'Invitation cancelled',
    'collaborator.team_add': 'Team given access',
    'collaborator.team_role': 'Team permission changed',
    'collaborator.team_remove': 'Team access removed',
    'pull_request.merge': 'Pull request merged',
    'pull_request.close': 'Pull request closed',
    'workflow.cancel': 'Workflow run cancelled',
    'api_token.create': 'API token created',
    'api_token.revoke': 'API token revoked',
}

RESULTS = {'': 'Any result', 'ok': 'Succeeded', 'failed': 'Failed'}
REPO_FILTER_PATTERN = re.compile(r'^[A-Za-z0-9._/-]{1,140}$')
ACTOR_PATTERN = re.compile(r'^[A-Za-z0-9 ()\[\]-]{1,60}$')


def record_audit(action, repo, ok, message='', target=None, installation_id=None, actor=None):
    """
    Add one audit entry. Installation and actor default to the signed-in session.
    Returns True if it was stored.
    """
    if action not in AUDIT_ACTIONS:
        raise ValueError(f"Unknown audit action '{action}'")
    if has_request_context():
        installation_id = installation_id or session.get('installation_id')
        actor = actor or session.get('github_user_login')
    if not installation_id or not actor:
        logging.error(f"Audit entry for {action} on {repo} has no installation or actor; not stored.")
        return False
    try:
        db = get_db()
        db.execute('INSERT INTO audit_log (installation_id, actor, action, repo, target, ok, message) '
                   'VALUES (?, ?, ?, ?, ?, ?, ?)',
                   (installation_id, actor, action, repo, target, 1 if ok else 0, (message or '')[:500]))
        db.commit()
        return True
    except Exception:
        logging.exception(f"Couldn't store audit entry for {action} on {repo}")
        return False


def parse_audit_filters(args):
    """Validated filters from the query string. Returns (filters, warnings)."""
    warnings = []
    filters = {'action': '', 'result': '', 'repo': '', 'actor': '', 'page': 1}

    action = (args.get('action') or '').strip()
    if action in AUDIT_ACTIONS:
        filters['action'] = action
    elif action:
        warnings.append(f"Ignored unknown action '{action}'.")

    result = (args.get('result') or '').strip()
    if result in RESULTS:
        filters['result'] = result
    else:
        warnings.append(f"Ignored unknown result '{result}'.")

    for key, pattern in (('repo', REPO_FILTER_PATTERN), ('actor', ACTOR_PATTERN)):
        value = (args.get(key) or '').strip()
        if value and pattern.match(value):
            filters[key] = value
        elif value:
            warnings.append(f"Ignored invalid {key} filter.")

    try:
        filters['page'] = max(1, int(args.get('page', 1)))
    except (TypeError, ValueError):
        pass
    return filters, warnings


def list_audit_entries(installation_id, filters, per_page=PER_PAGE):
    """Newest first. Returns (rows, total)."""
    where, params = ['installation_id = ?'], [installation_id]
    if filters.get('action'):
        where.append('action = ?')
        params.append(filters['action'])
    if filters.get('result'):
        where.append('ok = ?')
        params.append(1 if filters['result'] == 'ok' else 0)
    if filters.get('repo'):
        # Substring match; escape LIKE wildcards in the user's text
        escaped = filters['repo'].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        where.append("repo LIKE ? ESCAPE '\\'")
        params.append(f'%{escaped}%')
    if filters.get('actor'):
        where.append('actor = ?')
        params.append(filters['actor'])

    clause = ' AND '.join(where)
    db = get_db()
    total = db.execute(f'SELECT COUNT(*) FROM audit_log WHERE {clause}', params).fetchone()[0]
    offset = (filters.get('page', 1) - 1) * per_page
    rows = db.execute(f'SELECT * FROM audit_log WHERE {clause} ORDER BY id DESC LIMIT ? OFFSET ?',
                      params + [per_page, offset]).fetchall()
    entries = []
    for row in rows:
        entry = dict(row)
        entry['label'] = AUDIT_ACTIONS.get(entry['action'], entry['action'])
        entry['ago'] = time_ago(parse_github_date(entry['created_at']))
        entries.append(entry)
    return entries, total
