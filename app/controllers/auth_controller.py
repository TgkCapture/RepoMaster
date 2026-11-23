import os
import requests
import logging
import time
from functools import lru_cache, wraps
from flask import session, current_app, request
from jose import jwt

REQUEST_TIMEOUT = 60  # seconds

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

def get_installation_access_token():
    """
    Exchange the JWT for an installation access token and retrieve the username and avatar URL.
    """
    installation_id = session.get('installation_id')

    if not installation_id:
        logging.error("Missing installation ID in session.")
        return None

    logging.info(f"Making POST request to GitHub API with installation ID: {installation_id}")
    jwt_token = get_jwt()

    token_url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
    headers = {
        'Authorization': f'Bearer {jwt_token}',
        'Accept': 'application/vnd.github+json',
    }

    try:
        token_response = requests.post(token_url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logging.error(f"Failed to reach GitHub for installation token: {e}")
        return None
    if token_response.status_code == 201:
        access_token = token_response.json().get('token')
        logging.info("Fetched GitHub App installation access token.")
        session['github_installation_token'] = access_token 

        # Get the username associated with the installation
        installation_url = f'https://api.github.com/app/installations/{installation_id}'
        try:
            installation_response = requests.get(installation_url, headers=headers, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as e:
            logging.error(f"Failed to reach GitHub for installation details: {e}")
            return access_token
        if installation_response.status_code == 200:
            user_data = installation_response.json().get('account', {})
            session['github_username'] = user_data.get('login')
            session['github_avatar_url'] = user_data.get('avatar_url')

        else:
            logging.error(f"Failed to retrieve installation details: {installation_response.status_code}, {installation_response.text}")

        return access_token
    else:
        logging.error(f"Failed to get installation token: {token_response.status_code}, {token_response.text}")
        return None

def is_user_logged_in():
    """
    Checks if the user is authenticated by verifying the presence of a valid installation access token.
    """
    access_token = session.get('github_installation_token')

    if access_token:
        logging.info("User is authenticated with a valid installation access token.")
        return True
    else:
        logging.warning("User is not authenticated. No installation access token found in the session.")
        return False

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
    Clears all session data (installation, token, username and avatar).
    """
    logging.info("Clearing session data for logout.")
    session.clear()