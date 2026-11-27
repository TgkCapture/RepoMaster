"""soft_delete_controller.py

Recoverable repository deletion (issue #51). Deleting a repository archives it straight
away (read-only on GitHub) and schedules the real deletion SOFT_DELETE_DAYS later.
Until then it can be undone, which unarchives it again (unless it was archived before).

Due deletions are carried out by `flask run-scheduled-deletions` (see app/commands.py),
which should run regularly, e.g. hourly from cron. Before deleting, it checks that the
repository is still archived: if someone unarchived it on GitHub, it is kept.
"""
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from flask import current_app, has_request_context, session
from app.db import get_db
from app.controllers.repo_controller import github_api
from app.controllers.audit_controller import SYSTEM_ACTOR, record_audit
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago

DEFAULT_SOFT_DELETE_DAYS = 7
OPEN_STATUSES = ('pending', 'failed')  # can still be undone
STATUS_LABELS = {
    'pending': 'Scheduled',
    'failed': 'Deletion failed',
    'cancelled': 'Undone',
    'deleted': 'Deleted',
    'skipped': 'Kept',
}


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _now():
    return datetime.now(timezone.utc)


def soft_delete_days():
    """Grace period from config; 0 means delete immediately."""
    try:
        return max(0, int(current_app.config.get('SOFT_DELETE_DAYS', DEFAULT_SOFT_DELETE_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_SOFT_DELETE_DAYS


def _repo_path(full_name):
    owner, _, repo = full_name.partition('/')
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


def _pending_for(installation_id, full_name):
    return get_db().execute(
        "SELECT * FROM scheduled_deletions WHERE installation_id = ? AND repo = ? AND status IN ('pending', 'failed')",
        (installation_id, full_name)).fetchone()


def schedule_deletion(owner, repo, access_token, days=None, installation_id=None, actor=None, now=None):
    """
    Archive the repository and schedule its deletion, or delete it at once when the grace
    period is 0. Returns (ok, message).
    """
    full_name = f'{owner}/{repo}'
    days = soft_delete_days() if days is None else days
    if has_request_context():
        installation_id = installation_id or session.get('installation_id')
        actor = actor or session.get('github_user_login')
    now = now or _now()

    existing = _pending_for(installation_id, full_name)
    if existing:
        return True, f"{full_name} is already scheduled for deletion."

    details, error = github_api('GET', _repo_path(full_name), access_token)
    if error:
        record_audit('repository.delete_scheduled', full_name, False, error, installation_id=installation_id, actor=actor)
        return False, error

    if days <= 0:
        _, error = github_api('DELETE', _repo_path(full_name), access_token)
        record_audit('repository.deleted', full_name, error is None, error or 'Deleted immediately (no grace period)',
                     installation_id=installation_id, actor=actor)
        return (False, error) if error else (True, f"{full_name} deleted.")

    was_archived = bool(details.get('archived'))
    if not was_archived:
        _, error = github_api('PATCH', _repo_path(full_name), access_token, json={'archived': True})
        if error:
            record_audit('repository.delete_scheduled', full_name, False, f"Couldn't archive: {error}",
                         installation_id=installation_id, actor=actor)
            return False, f"Couldn't archive it first: {error}"

    delete_after = now + timedelta(days=days)
    db = get_db()
    db.execute('INSERT INTO scheduled_deletions (installation_id, repo, requested_by, requested_at, delete_after, '
               'was_archived) VALUES (?, ?, ?, ?, ?, ?)',
               (installation_id, full_name, actor, _iso(now), _iso(delete_after), 1 if was_archived else 0))
    db.commit()
    when = delete_after.strftime('%Y-%m-%d %H:%M UTC')
    record_audit('repository.delete_scheduled', full_name, True, f"Archived; will be deleted after {when}",
                 installation_id=installation_id, actor=actor)
    return True, f"{full_name} archived and scheduled for deletion after {when}."


def cancel_deletion(deletion_id, installation_id, access_token, now=None):
    """Undo a scheduled (or failed) deletion. Returns (ok, message)."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM scheduled_deletions WHERE id = ? AND installation_id = ? AND status IN ('pending', 'failed')",
        (deletion_id, installation_id)).fetchone()
    if row is None:
        return False, "There's no scheduled deletion to undo."

    if not row['was_archived']:
        _, error = github_api('PATCH', _repo_path(row['repo']), access_token, json={'archived': False})
        if error:
            record_audit('repository.delete_cancelled', row['repo'], False, f"Couldn't unarchive: {error}")
            return False, f"Couldn't unarchive {row['repo']}: {error}"

    db.execute("UPDATE scheduled_deletions SET status = 'cancelled', finished_at = ?, message = ? WHERE id = ?",
               (_iso(now or _now()), 'Undone', deletion_id))
    db.commit()
    kept = 'restored' if not row['was_archived'] else 'kept (it stays archived, as it was before)'
    record_audit('repository.delete_cancelled', row['repo'], True, f"Deletion undone; repository {kept}")
    return True, f"Deletion of {row['repo']} undone; the repository is {kept}."


def _finish(row, status, message, now):
    db = get_db()
    db.execute('UPDATE scheduled_deletions SET status = ?, finished_at = ?, message = ? WHERE id = ?',
               (status, _iso(now), message, row['id']))
    db.commit()


def run_due_deletions(get_token, now=None):
    """
    Delete every repository whose grace period is over. `get_token(installation_id)` returns
    an installation access token or None. Returns a list of (repo, status, message).
    """
    now = now or _now()
    rows = get_db().execute(
        "SELECT * FROM scheduled_deletions WHERE status = 'pending' AND delete_after <= ? ORDER BY delete_after",
        (_iso(now),)).fetchall()
    tokens, results = {}, []

    for row in rows:
        installation_id = row['installation_id']
        if installation_id not in tokens:
            tokens[installation_id] = get_token(installation_id)
        token = tokens[installation_id]
        audit = {'installation_id': installation_id, 'actor': SYSTEM_ACTOR}
        if not token:
            # Left pending: retried on the next run
            logging.error(f"No token for installation {installation_id}; deletion of {row['repo']} postponed.")
            results.append((row['repo'], 'pending', 'No access token; will retry'))
            continue

        details, error = github_api('GET', _repo_path(row['repo']), token)
        if error in ('Not Found', 'GitHub returned status 404'):
            status, message, action, ok = 'skipped', 'Repository no longer exists', 'repository.delete_kept', True
        elif error:
            status, message, action, ok = 'failed', error, 'repository.deleted', False
        elif not details.get('archived'):
            status, message, action, ok = ('skipped', 'It was unarchived on GitHub, so it was kept',
                                           'repository.delete_kept', True)
        else:
            _, error = github_api('DELETE', _repo_path(row['repo']), token)
            if error:
                status, message, action, ok = 'failed', error, 'repository.deleted', False
            else:
                status, message, action, ok = ('deleted', f"Deleted as requested by {row['requested_by']}",
                                               'repository.deleted', True)

        _finish(row, status, message, now)
        record_audit(action, row['repo'], ok, message, **audit)
        results.append((row['repo'], status, message))
    return results


def list_deletions(installation_id, limit=50):
    """Open deletions first (soonest first), then the most recent finished ones."""
    rows = get_db().execute(
        "SELECT * FROM scheduled_deletions WHERE installation_id = ? "
        "ORDER BY status NOT IN ('pending', 'failed'), "
        "CASE WHEN status IN ('pending', 'failed') THEN delete_after END, id DESC LIMIT ?",
        (installation_id, limit)).fetchall()
    deletions = []
    for row in rows:
        entry = dict(row)
        entry['open'] = entry['status'] in OPEN_STATUSES
        entry['status_label'] = STATUS_LABELS.get(entry['status'], entry['status'])
        entry['delete_after_display'] = entry['delete_after'].replace('T', ' ').replace('Z', ' UTC')
        entry['requested_ago'] = time_ago(parse_github_date(entry['requested_at']))
        deletions.append(entry)
    return deletions
