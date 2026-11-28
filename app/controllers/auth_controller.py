"""auth_controller.py

Two kinds of GitHub authentication are used:

* User sign-in (OAuth, user-to-server): proves *who* the visitor is, and lets us ask
  GitHub which App installations that user can access. Only such an installation is
  ever stored in the session, so a visitor cannot use someone else's installation
  by guessing its ID.
* App installation tokens (JWT -> installation access token): used for the actual
  repository API calls on the verified installation.
"""
import os
import hmac
import secrets
import requests
from app import github_http, token_cache
import logging
import time
from functools import lru_cache, wraps
from urllib.parse import urlencode
from flask import session, current_app, request, url_for
from jose import jwt

REQUEST_TIMEOUT = 60  # seconds
GITHUB_API_URL = 'https://api.github.com'
OAUTH_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
OAUTH_TOKEN_URL = 'https://github.com/login/oauth/access_token'

# --- GitHub App (installation) authentication --------------------------------

@lru_cache(maxsize=1)
def load_private_key(private_key_path):
    """
    Read the GitHub App private key from disk (cached after the first read).
    """
    if private_key_path and os.path.exists(private_key_path):
        with open(private_key_path, 'r') as f:
            return f.read()
    raise FileNotFoundError(f"Private key file not found at {private_key_path}")

def get_jwt():
    """
    Generate a JWT for GitHub App authentication.
    """
    app_id = int(current_app.config['GITHUB_APP_ID'])
    private_key = load_private_key(current_app.config['GITHUB_PRIVATE_KEY_PATH'])
    payload = {
        'iat': int(time.time()),
        'exp': int(time.time()) + 600,  # Token valid for 10 minutes
        'iss': app_id,
    }
    token = jwt.encode(payload, private_key, algorithm='RS256')
    logging.info("Generated JWT for GitHub App.")
    return token

def get_installation_access_token(installation_id=None):
    """
    Exchange the JWT for an access token for the session's verified installation, or for
    `installation_id` when given (background jobs, which have no session).
    Tokens are cached until shortly before they expire (see token_cache).
    """
    installation_id = installation_id or session.get('installation_id')

    if not installation_id:
        logging.error("Missing installation ID in session.")
        return None

    cached = token_cache.get(installation_id)
    if cached:
        return cached

    logging.info(f"Requesting access token for installation ID: {installation_id}")
    jwt_token = get_jwt()

    token_url = f'{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens'
    headers = {
        'Authorization': f'Bearer {jwt_token}',
        'Accept': 'application/vnd.github+json',
    }

    try:
        token_response = github_http.post(token_url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logging.error(f"Failed to reach GitHub for installation token: {e}")
        return None

    if token_response.status_code == 201:
        logging.info("Fetched GitHub App installation access token.")
        data = token_response.json()
        token = data.get('token')
        if token:
            token_cache.put(installation_id, token, data.get('expires_at'))
        return token

    logging.error(f"Failed to get installation token: {token_response.status_code}, {token_response.text}")
    return None

# --- User sign-in (OAuth) ----------------------------------------------------

def oauth_callback_url():
    """The OAuth redirect URI. Must match the Callback URL configured on the GitHub App."""
    return current_app.config.get('GITHUB_OAUTH_CALLBACK_URL') or url_for('main.github_callback', _external=True)

OAUTH_PURPOSE_LOGIN = 'login'
OAUTH_PURPOSE_CREATE_REPOSITORY = 'create_repository'

def generate_oauth_state(purpose=OAUTH_PURPOSE_LOGIN):
    """
    Create a one-time CSRF token for the OAuth round trip and remember it, together with
    what the round trip is for, in the session.
    """
    state = secrets.token_urlsafe(32)
    session['oauth_state'] = state
    session['oauth_purpose'] = purpose
    return state

def validate_oauth_state(received_state):
    """
    Check the state GitHub sent back against the one we issued. The stored state is
    consumed, so each one can only be used once.
    Returns the purpose the state was issued for, or None if it doesn't match.
    """
    expected_state = session.pop('oauth_state', None)
    purpose = session.pop('oauth_purpose', None) or OAUTH_PURPOSE_LOGIN
    if not expected_state or not received_state:
        return None
    return purpose if hmac.compare_digest(expected_state, received_state) else None

def build_authorize_url(state, redirect_uri):
    """
    URL that sends the user to GitHub to sign in to the GitHub App.
    """
    params = {
        'client_id': current_app.config['GITHUB_CLIENT_ID'],
        'redirect_uri': redirect_uri,
        'state': state,
    }
    return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

def exchange_code_for_user_token(code, redirect_uri):
    """
    Exchange the OAuth `code` from the callback for a user access token.
    Returns the token, or None on failure.
    """
    data = {
        'client_id': current_app.config['GITHUB_CLIENT_ID'],
        'client_secret': current_app.config['GITHUB_CLIENT_SECRET'],
        'code': code,
        'redirect_uri': redirect_uri,
    }
    try:
        response = github_http.post(OAUTH_TOKEN_URL, data=data, headers={'Accept': 'application/json'},
                                 timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to exchange OAuth code: {e}")
        return None

    payload = response.json()
    # GitHub reports OAuth errors with a 200 status and an `error` field
    if 'error' in payload:
        logging.error(f"OAuth code exchange rejected: {payload.get('error')}: {payload.get('error_description')}")
        return None
    return payload.get('access_token')

def _user_api_get(user_token, path, params=None):
    headers = {
        'Authorization': f'Bearer {user_token}',
        'Accept': 'application/vnd.github+json',
    }
    response = github_http.get(f'{GITHUB_API_URL}{path}', headers=headers, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()

def get_authenticated_user(user_token):
    """
    The GitHub user who owns the user access token, or None on failure.
    """
    try:
        return _user_api_get(user_token, '/user')
    except requests.RequestException as e:
        logging.error(f"Failed to fetch the authenticated user: {e}")
        return None

def get_user_installations(user_token):
    """
    Installations of this GitHub App that the user can access, or None on failure.
    """
    try:
        return _user_api_get(user_token, '/user/installations', params={'per_page': 100}).get('installations', [])
    except requests.RequestException as e:
        logging.error(f"Failed to fetch the user's installations: {e}")
        return None

def choose_installation(installations, user_login, requested_installation_id=None, previous_installation_id=None):
    """
    Pick the installation to use from those the user can access.

    If a specific installation was requested (e.g. right after installing the App), it
    is returned only if it is in the user's list. Otherwise the installation used before
    signing in again is kept if still available, then the user's personal-account
    installation is preferred, then the first available one.
    """
    if requested_installation_id is not None:
        for installation in installations:
            if str(installation.get('id')) == str(requested_installation_id):
                return installation
        return None

    if previous_installation_id is not None:
        for installation in installations:
            if str(installation.get('id')) == str(previous_installation_id):
                return installation

    for installation in installations:
        if installation.get('account', {}).get('login') == user_login:
            return installation
    return installations[0] if installations else None

# The session is a signed cookie, so keep the list of switchable accounts small
MAX_SWITCHABLE_INSTALLATIONS = 25

# Session keys that belong to the selected installation and must not follow a switch
INSTALLATION_SCOPED_KEYS = ('pending_repository', 'repository_creation_result')


def summarize_installations(installations, user_login):
    """
    The installations the user verified at sign-in, compacted for the session:
    [{'id', 'login', 'type', 'account_id'}], the user's own account first, then by name.
    """
    rows = []
    for installation in installations or []:
        account = installation.get('account') or {}
        if installation.get('id') is None or not account.get('login'):
            continue
        rows.append({'id': installation['id'], 'login': account['login'],
                     'type': account.get('type') or 'User', 'account_id': account.get('id')})
    rows.sort(key=lambda row: (row['login'].lower() != (user_login or '').lower(), row['login'].lower()))
    return rows[:MAX_SWITCHABLE_INSTALLATIONS]


def account_avatar_url(account_id, size=40):
    """GitHub avatar for a user or organization, from its numeric id."""
    if not account_id:
        return None
    return f'https://avatars.githubusercontent.com/u/{int(account_id)}?s={int(size)}&v=4'


def _select_installation(installation_id, login, account_type):
    session['installation_id'] = installation_id
    # Owner of the repositories the installation manages (user or organization)
    session['github_username'] = login
    session['github_account_type'] = account_type  # 'User' or 'Organization'


def start_user_session(user, installation, installations=None):
    """
    Replace the session with a fresh, verified login. `installations` are all the
    installations GitHub says the user can access; they become the account switcher.
    """
    session.clear()
    account = installation.get('account', {})
    session['github_user_login'] = user.get('login')
    session['github_avatar_url'] = user.get('avatar_url')
    _select_installation(installation.get('id'), account.get('login'), account.get('type'))
    session['installations'] = summarize_installations(installations or [installation], user.get('login'))
    logging.info(f"User '{user.get('login')}' signed in with installation {installation.get('id')} "
                 f"on account '{account.get('login')}'.")


def available_installations():
    """The installations verified at sign-in (see start_user_session)."""
    return session.get('installations') or []


def switch_installation(installation_id):
    """
    Make another verified installation the active one. Only installations GitHub listed
    for this user at sign-in are accepted. Returns the selected entry, or None.
    """
    for entry in available_installations():
        if str(entry['id']) == str(installation_id):
            for key in INSTALLATION_SCOPED_KEYS:
                session.pop(key, None)
            _select_installation(entry['id'], entry['login'], entry['type'])
            logging.info(f"User '{session.get('github_user_login')}' switched to installation {entry['id']} "
                         f"on account '{entry['login']}'.")
            return entry
    return None

# --- Session helpers ----------------------------------------------------------

def is_user_logged_in():
    """
    True when the user signed in through GitHub and has a verified installation.
    """
    return bool(session.get('github_user_login') and session.get('installation_id'))

def login_required(view):
    """
    Route decorator: respond 403 unless the user is logged in.
    """
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_user_logged_in():
            logging.warning(f"Unauthenticated access attempt to '{request.path}'.")
            return "You are not logged in", 403
        return view(*args, **kwargs)
    return wrapped_view

def clear_session():
    """
    Clears all session data (user, installation, username and avatar).
    """
    logging.info("Clearing session data for logout.")
    session.clear()
