"""jobs_controller.py

Background jobs with progress reporting (issue #54), used for bulk repository actions.

A job runs in a background thread of the web process, with its own app context, and
saves its progress and results in the `jobs` table after every repository, so the
progress page can poll it. No queue server (Redis/RQ/Celery) is needed. A job is lost if
the process restarts while it runs; it then shows as interrupted, with the results it
had saved.
"""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.db import get_db

ACTIVE_STATUSES = ('queued', 'running')
STALE_AFTER = timedelta(minutes=10)   # no progress for this long while running = interrupted
STATUS_LABELS = {'queued': 'Queued', 'running': 'Running', 'finished': 'Finished', 'failed': 'Failed',
                 'interrupted': 'Interrupted'}
RECENT_JOBS = 20


def _stamp(now=None):
    return (now or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')


def create_job(installation_id, created_by, kind, title, total):
    db = get_db()
    now = _stamp()
    with db:
        cursor = db.execute('INSERT INTO jobs (installation_id, created_by, kind, title, total, created_at, updated_at) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?)', (installation_id, created_by, kind, title, total, now, now))
    return cursor.lastrowid


def save_progress(job_id, results):
    db = get_db()
    with db:
        db.execute("UPDATE jobs SET status = 'running', done = ?, results = ?, updated_at = ? WHERE id = ?",
                   (len(results), json.dumps(results), _stamp(), job_id))


def finish_job(job_id, results=None, error=None):
    """Mark the job finished (or failed, with `error`). Results default to what was last saved."""
    db = get_db()
    now = _stamp()
    with db:
        if results is None:
            db.execute('UPDATE jobs SET status = ?, error = ?, updated_at = ?, finished_at = ? WHERE id = ?',
                       ('failed' if error else 'finished', error, now, now, job_id))
        else:
            db.execute('UPDATE jobs SET status = ?, error = ?, done = ?, results = ?, updated_at = ?, '
                       'finished_at = ? WHERE id = ?',
                       ('failed' if error else 'finished', error, len(results), json.dumps(results), now, now, job_id))


def _present(row, now):
    job = dict(row)
    job['results'] = json.loads(job['results'] or '[]')
    job['succeeded'] = sum(1 for result in job['results'] if result.get('ok'))
    updated = datetime.strptime(job['updated_at'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    if job['status'] in ACTIVE_STATUSES and now - updated > STALE_AFTER:
        job['status'] = 'interrupted'
    job['active'] = job['status'] in ACTIVE_STATUSES
    job['status_label'] = STATUS_LABELS.get(job['status'], job['status'])
    job['percent'] = int(100 * job['done'] / job['total']) if job['total'] else 100
    return job


def get_job(job_id, installation_id, now=None):
    """One of the installation's jobs, or None."""
    row = get_db().execute('SELECT * FROM jobs WHERE id = ? AND installation_id = ?',
                           (job_id, installation_id)).fetchone()
    return _present(row, now or datetime.now(timezone.utc)) if row else None


def list_jobs(installation_id, limit=RECENT_JOBS, now=None):
    rows = get_db().execute('SELECT * FROM jobs WHERE installation_id = ? ORDER BY id DESC LIMIT ?',
                            (installation_id, limit)).fetchall()
    now = now or datetime.now(timezone.utc)
    return [_present(row, now) for row in rows]


def start_job(job_id, target, *args):
    """
    Run target(job_id, *args) in a background thread with an app context. A crash marks
    the job failed, keeping the results saved so far. With BACKGROUND_JOBS_SYNC it runs
    before returning instead.
    """
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            try:
                target(job_id, *args)
            except Exception:
                logging.exception(f"Background job {job_id} failed")
                try:
                    finish_job(job_id, error="Stopped by an unexpected error. Results so far are shown.")
                except Exception:
                    logging.exception(f"Couldn't mark job {job_id} as failed")

    if app.config.get('BACKGROUND_JOBS_SYNC'):
        run()
    else:
        threading.Thread(target=run, name=f'repomaster-job-{job_id}', daemon=True).start()
