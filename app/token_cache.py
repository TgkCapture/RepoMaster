"""token_cache.py

In-memory cache of GitHub App installation access tokens (issue #54).

Installation tokens last an hour. Without a cache every page asked GitHub for a new one,
often several times per page. Tokens are reused until REFRESH_MARGIN before they expire,
and dropped early if GitHub rejects one (see github_http). The cache is per process:
each web worker keeps its own, which is fine because any number of tokens may be valid
at once.
"""
import threading
import time
from datetime import datetime, timezone

REFRESH_MARGIN = 5 * 60          # seconds before expiry when a token is replaced
DEFAULT_LIFETIME = 60 * 60       # if GitHub doesn't say when the token expires

_lock = threading.Lock()
_by_installation = {}            # installation id (str) -> (token, expires_at epoch seconds)


def _parse_expiry(expires_at, now):
    try:
        return datetime.strptime(expires_at, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return now + DEFAULT_LIFETIME


def get(installation_id, now=None):
    """A cached token that is still good for at least REFRESH_MARGIN, or None."""
    now = time.time() if now is None else now
    with _lock:
        entry = _by_installation.get(str(installation_id))
    if entry and entry[1] - REFRESH_MARGIN > now:
        return entry[0]
    return None


def put(installation_id, token, expires_at=None, now=None):
    """Remember a token. `expires_at` is GitHub's ISO timestamp."""
    now = time.time() if now is None else now
    with _lock:
        _by_installation[str(installation_id)] = (token, _parse_expiry(expires_at, now))


def forget_token(token):
    """Drop a token GitHub rejected, so the next request fetches a new one."""
    with _lock:
        for installation_id, (cached, _) in list(_by_installation.items()):
            if cached == token:
                del _by_installation[installation_id]


def clear():
    with _lock:
        _by_installation.clear()
