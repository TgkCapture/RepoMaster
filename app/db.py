"""db.py

A small SQLite database (Python's built-in sqlite3) for data RepoMaster has to keep
between requests: notifications created from GitHub webhooks (issue #46), the audit log
and scheduled repository deletions (issue #51), API tokens (issue #53) and background
jobs (issue #54).

The file lives at DATABASE_PATH, or <instance folder>/repomaster.db by default.
One connection per request, closed when the app context ends.
"""
import os
import sqlite3
from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    installation_id INTEGER NOT NULL,
    delivery_id     TEXT UNIQUE,
    event           TEXT NOT NULL,
    repo            TEXT,
    title           TEXT NOT NULL,
    link            TEXT,
    actor           TEXT,
    level           TEXT NOT NULL DEFAULT 'info',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    read            INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS notifications_by_installation
    ON notifications (installation_id, read, id DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    installation_id INTEGER NOT NULL,
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    repo            TEXT,
    target          TEXT,
    ok              INTEGER NOT NULL,
    message         TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS audit_log_by_installation
    ON audit_log (installation_id, id DESC);

CREATE TABLE IF NOT EXISTS scheduled_deletions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    installation_id INTEGER NOT NULL,
    repo            TEXT NOT NULL,
    requested_by    TEXT NOT NULL,
    requested_at    TEXT NOT NULL,
    delete_after    TEXT NOT NULL,
    was_archived    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',
    finished_at     TEXT,
    message         TEXT
);
CREATE INDEX IF NOT EXISTS scheduled_deletions_due
    ON scheduled_deletions (status, delete_after);

CREATE TABLE IF NOT EXISTS api_tokens (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    installation_id INTEGER NOT NULL,
    account         TEXT NOT NULL,
    account_type    TEXT,
    created_by      TEXT NOT NULL,
    name            TEXT NOT NULL,
    token_hash      TEXT NOT NULL UNIQUE,
    prefix          TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    last_used_at    TEXT,
    revoked_at      TEXT
);
CREATE INDEX IF NOT EXISTS api_tokens_by_installation
    ON api_tokens (installation_id, id DESC);

CREATE TABLE IF NOT EXISTS jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    installation_id INTEGER NOT NULL,
    created_by      TEXT NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    total           INTEGER NOT NULL,
    done            INTEGER NOT NULL DEFAULT 0,
    results         TEXT NOT NULL DEFAULT '[]',
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    finished_at     TEXT
);
CREATE INDEX IF NOT EXISTS jobs_by_installation
    ON jobs (installation_id, id DESC);
"""


def database_path(app):
    return app.config.get('DATABASE_PATH') or os.path.join(app.instance_path, 'repomaster.db')


def _connect(path):
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(app):
    """Create the database file and tables if needed, and close connections after each request."""
    path = database_path(app)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with _connect(path) as connection:
        connection.executescript(SCHEMA)
    connection.close()
    app.teardown_appcontext(close_db)


def get_db():
    if 'db' not in g:
        g.db = _connect(database_path(current_app))
    return g.db


def close_db(exception=None):
    connection = g.pop('db', None)
    if connection is not None:
        connection.close()
