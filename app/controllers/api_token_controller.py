"""api_token_controller.py

Personal API tokens for the JSON API (issue #53).

A signed-in user creates a token for the account (installation) they are using. The
token is shown once; only its SHA-256 hash is stored, plus a short prefix so the user
can tell tokens apart. API requests send it as `Authorization: Bearer <token>` and act
as that installation, read-only.
"""
import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timezone

from app.db import get_db

TOKEN_PREFIX = 'rm_'
PREFIX_SHOWN = 10                 # 'rm_' + 7 characters, enough to recognise a token
MAX_NAME_LENGTH = 60
MAX_ACTIVE_TOKENS = 20            # per installation
LAST_USED_RESOLUTION_SECONDS = 60  # don't write last_used_at on every request


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def hash_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def validate_token_name(name):
    """Returns (clean name, None) or (None, error)."""
    name = ' '.join((name or '').split())
    if not name:
        return None, "Give the token a name, such as the tool that will use it."
    if len(name) > MAX_NAME_LENGTH:
        return None, f"The name can be at most {MAX_NAME_LENGTH} characters."
    return name, None


def list_tokens(installation_id):
    """The installation's tokens, newest first (revoked ones included, marked)."""
    rows = get_db().execute(
        'SELECT id, name, prefix, created_by, created_at, last_used_at, revoked_at FROM api_tokens '
        'WHERE installation_id = ? ORDER BY id DESC', (installation_id,)).fetchall()
    return [dict(row) for row in rows]


def create_token(installation_id, account, account_type, created_by, name):
    """
    Create a token. Returns (token, None) - the only time the plain token is available -
    or (None, error).
    """
    name, error = validate_token_name(name)
    if error:
        return None, error
    db = get_db()
    active = db.execute('SELECT COUNT(*) FROM api_tokens WHERE installation_id = ? AND revoked_at IS NULL',
                        (installation_id,)).fetchone()[0]
    if active >= MAX_ACTIVE_TOKENS:
        return None, f"This account already has {MAX_ACTIVE_TOKENS} active tokens. Revoke one first."

    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    try:
        with db:
            db.execute(
                'INSERT INTO api_tokens (installation_id, account, account_type, created_by, name, token_hash, '
                'prefix, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (installation_id, account, account_type, created_by, name, hash_token(token),
                 token[:PREFIX_SHOWN], _now()))
    except sqlite3.Error as e:
        logging.error(f"Couldn't store API token: {e}")
        return None, "Couldn't save the token. Please try again."
    return token, None


def revoke_token(token_id, installation_id):
    """Revoke one of the installation's tokens. Returns True if it was active and is now revoked."""
    db = get_db()
    with db:
        cursor = db.execute('UPDATE api_tokens SET revoked_at = ? WHERE id = ? AND installation_id = ? '
                            'AND revoked_at IS NULL', (_now(), token_id, installation_id))
    return cursor.rowcount == 1


def authenticate_token(token, now=None):
    """
    The active token record for a presented token ({id, installation_id, account, account_type,
    name, created_by}), or None. Also notes when it was last used.
    """
    if not token or not token.startswith(TOKEN_PREFIX) or len(token) > 200:
        return None
    db = get_db()
    row = db.execute('SELECT id, installation_id, account, account_type, name, created_by, last_used_at '
                     'FROM api_tokens WHERE token_hash = ? AND revoked_at IS NULL',
                     (hash_token(token),)).fetchone()
    if row is None:
        return None
    record = dict(row)
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    last = record.pop('last_used_at')
    try:
        stale = last is None or (now - datetime.strptime(last, '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=timezone.utc)).total_seconds() >= LAST_USED_RESOLUTION_SECONDS
        if stale:
            with db:
                db.execute('UPDATE api_tokens SET last_used_at = ? WHERE id = ?', (stamp, record['id']))
    except (ValueError, sqlite3.Error) as e:
        logging.warning(f"Couldn't update API token last use: {e}")
    return record
