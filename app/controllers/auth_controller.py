import requests
import logging
import time
from flask import session
from app.config.github_app_config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY
from jose import jwt

def get_jwt():
    """
    Generate a JWT for GitHub App authentication.
    """
    app_id = int(GITHUB_APP_ID)
    payload = {
        'iat': int(time.time()),
        'exp': int(time.time()) + 600,  # Token valid for 10 minutes
        'iss': app_id,
    }
    token = jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm='RS256')
    logging.info("Generated JWT for GitHub App.")
    return token

def get_installation_access_token():
    """
    Exchange the JWT for an installation access token and retrieve the username and avatar URL.
    """
    jwt_token = get_jwt()
    installation_id = session.get('installation_id') 

    logging.info(f"Making POST request to GitHub API with installation ID: {installation_id}")

    if not installation_id:
        logging.error("Missing installation ID in session.")
        return None

    token_url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
    headers = {
        'Authorization': f'Bearer {jwt_token}',
        'Accept': 'application/vnd.github+json',
    }

    token_response = requests.post(token_url, headers=headers)
    if token_response.status_code == 201:
        access_token = token_response.json().get('token')
        logging.info("Fetched GitHub App installation access token.")
        session['github_installation_token'] = access_token 

        # Get the username associated with the installation
        installation_url = f'https://api.github.com/app/installations/{installation_id}'
        installation_response = requests.get(installation_url, headers=headers)
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

def clear_session():
    """
    Clears all GitHub authentication-related session data.
    """
    logging.info("Clearing session data for logout.")
    session.pop('installation_id', None)
    session.pop('github_installation_token', None)
    session.pop('github_username', None)