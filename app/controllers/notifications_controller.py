"""notifications_controller.py

GitHub webhook handling and in-app notifications (issue #46).

GitHub sends App events to POST /github/webhook. Each delivery is verified with the
webhook secret (X-Hub-Signature-256), turned into at most one notification, and stored
per installation, so everyone signed in to that installation sees it.
"""
import hashlib
import hmac
from flask import url_for
from app.db import get_db

MAX_PER_INSTALLATION = 500
FAILED_CONCLUSIONS = ('failure', 'timed_out', 'startup_failure')
HANDLED_EVENTS = ('installation', 'push', 'pull_request', 'issues', 'workflow_run', 'check_run')


# --- Verification ------------------------------------------------------------

def verify_signature(secret, body, signature_header):
    """True if X-Hub-Signature-256 is the HMAC-SHA256 of the raw body with our secret."""
    if not secret or not signature_header or not signature_header.startswith('sha256='):
        return False
    expected = 'sha256=' + hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


# --- Turning events into notifications ---------------------------------------

def _login(user):
    return (user or {}).get('login') or 'someone'


def _branch(ref):
    return (ref or '').removeprefix('refs/heads/')


def _repo_names(payload):
    repository = payload.get('repository') or {}
    return repository.get('full_name'), repository.get('name')


def _pull_request(payload):
    action, pr = payload.get('action'), payload.get('pull_request') or {}
    full_name, name = _repo_names(payload)
    number, title = pr.get('number'), pr.get('title') or ''
    link = url_for('main.manage_pull_requests', repo_name=name, pr_number=number) if name and number else None
    actor = _login(payload.get('sender'))
    if action == 'opened':
        return {'title': f"{actor} opened PR #{number}: {title}", 'link': link, 'level': 'info'}
    if action == 'ready_for_review':
        return {'title': f"PR #{number} is ready for review: {title}", 'link': link, 'level': 'info'}
    if action == 'review_requested':
        reviewer = _login(payload.get('requested_reviewer')) if payload.get('requested_reviewer') \
            else (payload.get('requested_team') or {}).get('name', 'a team')
        return {'title': f"PR #{number} needs review from {reviewer}: {title}", 'link': link, 'level': 'warning'}
    if action == 'closed':
        verb = 'merged' if pr.get('merged') else 'closed'
        return {'title': f"{actor} {verb} PR #{number}: {title}", 'link': link,
                'level': 'success' if pr.get('merged') else 'info'}
    if action == 'reopened':
        return {'title': f"{actor} reopened PR #{number}: {title}", 'link': link, 'level': 'info'}
    return None


def _issues(payload):
    action, issue = payload.get('action'), payload.get('issue') or {}
    _, name = _repo_names(payload)
    number, title = issue.get('number'), issue.get('title') or ''
    link = url_for('main.issue_detail', repo_name=name, issue_number=number) if name and number else None
    actor = _login(payload.get('sender'))
    if action in ('opened', 'closed', 'reopened'):
        return {'title': f"{actor} {action} issue #{number}: {title}", 'link': link, 'level': 'info'}
    if action == 'assigned':
        return {'title': f"Issue #{number} was assigned to {_login(payload.get('assignee'))}: {title}",
                'link': link, 'level': 'info'}
    return None


def _push(payload):
    if payload.get('deleted') or not payload.get('commits'):
        return None
    count = len(payload['commits'])
    branch = _branch(payload.get('ref'))
    actor = (payload.get('pusher') or {}).get('name') or _login(payload.get('sender'))
    compare = payload.get('compare')
    return {'title': f"{actor} pushed {count} commit{'s' if count != 1 else ''} to {branch}",
            'link': compare if (compare or '').startswith('https://github.com/') else None, 'level': 'info'}


def _workflow_run(payload):
    run = payload.get('workflow_run') or {}
    if payload.get('action') != 'completed' or run.get('conclusion') not in FAILED_CONCLUSIONS:
        return None
    full_name, _ = _repo_names(payload)
    owner, _, repo = (full_name or '').partition('/')
    link = url_for('main.actions_run', owner=owner, repo=repo, run_id=run['id']) if owner and repo and run.get('id') else None
    return {'title': f"CI failed on {run.get('head_branch')}: {run.get('name')} #{run.get('run_number')}",
            'link': link, 'level': 'danger'}


def _check_run(payload):
    check = payload.get('check_run') or {}
    # Checks created by GitHub Actions are already reported through workflow_run
    if (check.get('app') or {}).get('slug') == 'github-actions':
        return None
    if payload.get('action') != 'completed' or check.get('conclusion') not in FAILED_CONCLUSIONS:
        return None
    branches = [b.get('name') for b in (check.get('check_suite') or {}).get('pull_requests') or []]
    where = (check.get('check_suite') or {}).get('head_branch') or (branches[0] if branches else 'a commit')
    link = check.get('html_url') if (check.get('html_url') or '').startswith('https://github.com/') else None
    return {'title': f"Check {check.get('name')} failed on {where}", 'link': link, 'level': 'danger'}


def _installation(payload):
    account = _login((payload.get('installation') or {}).get('account'))
    if payload.get('action') == 'created':
        return {'title': f"RepoMaster was installed on {account}", 'link': None, 'level': 'success'}
    if payload.get('action') in ('suspend', 'unsuspend'):
        return {'title': f"RepoMaster was {payload['action']}ed on {account}", 'link': None, 'level': 'warning'}
    return None


BUILDERS = {'pull_request': _pull_request, 'issues': _issues, 'push': _push,
            'workflow_run': _workflow_run, 'check_run': _check_run, 'installation': _installation}


def build_notification(event, payload):
    """The notification for one event, or None if the event isn't worth telling anyone about."""
    builder = BUILDERS.get(event)
    if builder is None:
        return None
    notification = builder(payload)
    if notification is None:
        return None
    full_name, _ = _repo_names(payload)
    notification['title'] = notification['title'][:300]
    notification.update(event=event, repo=full_name, actor=_login(payload.get('sender')))
    return notification


# --- Storage -----------------------------------------------------------------

def handle_delivery(event, delivery_id, payload):
    """Process one verified delivery. Returns a short description of what happened."""
    if event == 'ping':
        return 'pong'
    installation_id = (payload.get('installation') or {}).get('id')
    if not isinstance(installation_id, int):
        return 'ignored: no installation'
    if event == 'installation' and payload.get('action') == 'deleted':
        db = get_db()
        db.execute('DELETE FROM notifications WHERE installation_id = ?', (installation_id,))
        db.commit()
        return 'installation removed'
    notification = build_notification(event, payload)
    if notification is None:
        return 'ignored'
    stored = add_notification(installation_id, delivery_id, notification)
    return 'stored' if stored else 'duplicate'


def add_notification(installation_id, delivery_id, notification):
    """Store a notification (GitHub redeliveries are ignored) and keep only the newest 500."""
    db = get_db()
    cursor = db.execute(
        'INSERT OR IGNORE INTO notifications (installation_id, delivery_id, event, repo, title, link, actor, level) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (installation_id, delivery_id, notification['event'], notification.get('repo'), notification['title'],
         notification.get('link'), notification.get('actor'), notification.get('level', 'info')))
    db.execute('DELETE FROM notifications WHERE installation_id = ? AND id NOT IN '
               '(SELECT id FROM notifications WHERE installation_id = ? ORDER BY id DESC LIMIT ?)',
               (installation_id, installation_id, MAX_PER_INSTALLATION))
    db.commit()
    return cursor.rowcount == 1


def list_notifications(installation_id, limit=100):
    rows = get_db().execute('SELECT * FROM notifications WHERE installation_id = ? ORDER BY id DESC LIMIT ?',
                            (installation_id, limit)).fetchall()
    return [dict(row) for row in rows]


def unread_count(installation_id):
    return get_db().execute('SELECT COUNT(*) FROM notifications WHERE installation_id = ? AND read = 0',
                            (installation_id,)).fetchone()[0]


def get_notification(installation_id, notification_id):
    row = get_db().execute('SELECT * FROM notifications WHERE installation_id = ? AND id = ?',
                           (installation_id, notification_id)).fetchone()
    return dict(row) if row else None


def mark_read(installation_id, notification_id=None):
    """Mark one notification (or all of them) as read, only within this installation."""
    db = get_db()
    if notification_id is None:
        db.execute('UPDATE notifications SET read = 1 WHERE installation_id = ?', (installation_id,))
    else:
        db.execute('UPDATE notifications SET read = 1 WHERE installation_id = ? AND id = ?',
                   (installation_id, notification_id))
    db.commit()


def safe_link(link):
    """Only follow links to RepoMaster's own pages or to github.com (no open redirects)."""
    link = link or ''
    if link.startswith('/') and not link.startswith('//') and '\\' not in link:
        return link
    if link.startswith('https://github.com/'):
        return link
    return None
