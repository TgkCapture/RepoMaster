"""github_http.py

The one HTTP client RepoMaster uses to talk to GitHub (issue #54). Drop-in functions
(request, get, post, put, patch, delete) with the same arguments as `requests`, adding:

- Connection reuse: one `requests.Session` per thread (sessions aren't guaranteed to be
  thread-safe), so keep-alive connections to api.github.com are reused.
- Conditional requests: successful authenticated GETs with an ETag are remembered, and
  repeated with If-None-Match. GitHub answers 304 Not Modified when nothing changed; that
  doesn't count against the rate limit and the cached body is returned. Data is never
  served without asking GitHub, so it can't go stale after a change.
- Rate limits: remaining quota is tracked and logged when low, rate-limit responses get
  a clear message (rate_limit_message), and retry_delay() tells background jobs how long
  to wait.
- No cookies: the session refuses cookies, so nothing from one user's request (e.g. the
  OAuth exchange on github.com) is ever sent with another user's.
- Rejected tokens: a 401 drops the token from the installation token cache.
"""
import hashlib
import http.cookiejar
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

import requests
from requests.structures import CaseInsensitiveDict

from app import token_cache

USER_AGENT = 'RepoMaster'
API_VERSION = '2022-11-28'
MAX_CACHE_ENTRIES = 500
MAX_CACHED_BODY_BYTES = 1024 * 1024
LOW_RATE_LIMIT = 100
CACHED_HEADERS = ('Content-Type', 'Link', 'ETag', 'Last-Modified')

_local = threading.local()
_cache_lock = threading.Lock()
_cache = OrderedDict()           # key -> {'etag', 'content', 'headers', 'encoding'}
_rate = {'remaining': None, 'limit': None, 'reset': None, 'warned_reset': None}


def session():
    """This thread's shared session."""
    current = getattr(_local, 'session', None)
    if current is None:
        current = requests.Session()
        current.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        current.headers.update({'User-Agent': USER_AGENT, 'X-GitHub-Api-Version': API_VERSION})
        _local.session = current
    return current


# --- Conditional request cache ----------------------------------------------

def _header(headers, name):
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            return value
    return None


def _cache_key(method, url, params, headers):
    """Only authenticated GETs are cached, keyed by the credentials so accounts never share entries."""
    authorization = _header(headers, 'Authorization')
    if method.upper() != 'GET' or not authorization:
        return None
    if isinstance(params, dict):
        params = sorted((str(k), str(v)) for k, v in params.items())
    credentials = hashlib.sha256(authorization.encode('utf-8')).hexdigest()
    return (credentials, url, repr(params), _header(headers, 'Accept') or '')


def _cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is not None:
            _cache.move_to_end(key)
        return entry


def _cache_put(key, response):
    content = response.content
    if len(content) > MAX_CACHED_BODY_BYTES:
        return
    headers = {name: response.headers[name] for name in CACHED_HEADERS if name in response.headers}
    with _cache_lock:
        _cache[key] = {'etag': response.headers['ETag'], 'content': content, 'headers': headers,
                       'encoding': response.encoding}
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)


def _from_cache(entry, not_modified):
    """A 200 response rebuilt from the cache, carrying the 304's fresh rate-limit headers."""
    response = requests.Response()
    response.status_code = 200
    response._content = entry['content']
    response.encoding = entry['encoding']
    response.headers = CaseInsensitiveDict(entry['headers'])
    for name, value in not_modified.headers.items():
        if name.lower().startswith('x-ratelimit'):
            response.headers[name] = value
    response.url = not_modified.url
    response.request = not_modified.request
    response.from_cache = True
    return response


def clear_cache():
    with _cache_lock:
        _cache.clear()


# --- Rate limits -------------------------------------------------------------

def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _note_rate_limit(response):
    headers = getattr(response, 'headers', None) or {}
    remaining = _int(headers.get('X-RateLimit-Remaining'))
    if remaining is None:
        return
    reset = _int(headers.get('X-RateLimit-Reset'))
    _rate.update(remaining=remaining, limit=_int(headers.get('X-RateLimit-Limit')), reset=reset)
    if remaining < LOW_RATE_LIMIT and _rate['warned_reset'] != reset:
        _rate['warned_reset'] = reset
        logging.warning(f"GitHub rate limit is low: {remaining} requests left until {_clock(reset)}.")


def _clock(epoch):
    if not epoch:
        return 'later'
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%H:%M UTC')


def rate_limit_status():
    """The last rate-limit numbers seen from GitHub: {'remaining', 'limit', 'reset'} (values may be None)."""
    return {key: _rate[key] for key in ('remaining', 'limit', 'reset')}


def retry_delay(response, now=None):
    """
    Seconds to wait before retrying if the response is a rate-limit refusal, else None.
    Uses Retry-After (secondary limits) or X-RateLimit-Reset (primary limit used up).
    """
    if getattr(response, 'status_code', None) not in (403, 429):
        return None
    headers = getattr(response, 'headers', None) or {}
    retry_after = _int(headers.get('Retry-After'))
    if retry_after is not None:
        return max(retry_after, 1)
    if headers.get('X-RateLimit-Remaining') == '0':
        now = time.time() if now is None else now
        reset = _int(headers.get('X-RateLimit-Reset'))
        return max(int(reset - now) + 1, 1) if reset else 60
    try:
        message = (response.json() or {}).get('message', '')
    except (ValueError, AttributeError):
        message = ''
    if 'secondary rate limit' in str(message).lower():
        return 60  # GitHub's advice when no Retry-After is given
    return None


def rate_limit_message(response):
    """A user-facing explanation if the response is a rate-limit refusal, else None."""
    delay = retry_delay(response)
    if delay is None:
        return None
    headers = getattr(response, 'headers', None) or {}
    if headers.get('X-RateLimit-Remaining') == '0' and _int(headers.get('X-RateLimit-Reset')):
        return f"GitHub's rate limit is used up. Try again after {_clock(_int(headers['X-RateLimit-Reset']))}."
    return f"GitHub is limiting requests right now. Try again in {delay} seconds."


def pop_rate_limited():
    """The retry delay of the last rate-limited response on this thread (then cleared), or None."""
    delay = getattr(_local, 'rate_limited', None)
    _local.rate_limited = None
    return delay


# --- Requests ----------------------------------------------------------------

def request(method, url, **kwargs):
    headers = dict(kwargs.pop('headers', None) or {})
    key = None if kwargs.get('stream') else _cache_key(method, url, kwargs.get('params'), headers)
    cached = _cache_get(key) if key else None
    if cached:
        headers['If-None-Match'] = cached['etag']

    response = session().request(method, url, headers=headers, **kwargs)
    _note_rate_limit(response)

    if cached and response.status_code == 304:
        return _from_cache(cached, response)
    if key and response.status_code == 200 and response.headers.get('ETag'):
        _cache_put(key, response)
    if response.status_code == 401:
        authorization = _header(headers, 'Authorization') or ''
        scheme, _, token = authorization.partition(' ')
        if token:
            token_cache.forget_token(token)
    delay = retry_delay(response)
    if delay is not None:
        _local.rate_limited = delay
        logging.warning(f"GitHub rate limit hit on {method} {url}; retry in {delay}s.")
    return response


def get(url, **kwargs):
    return request('GET', url, **kwargs)


def post(url, **kwargs):
    return request('POST', url, **kwargs)


def put(url, **kwargs):
    return request('PUT', url, **kwargs)


def patch(url, **kwargs):
    return request('PATCH', url, **kwargs)


def delete(url, **kwargs):
    return request('DELETE', url, **kwargs)
