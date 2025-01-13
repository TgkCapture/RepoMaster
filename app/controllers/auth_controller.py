"""auth_controller.py
"""

import requests
import logging
from flask import Blueprint, session, request
from app.config.oauth_config import github
from app.config.github_app_config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY
from jose import jwt
import time

auth_controller = Blueprint('authorize', __name__)
auth_controller.secret_key = '123456'


def get_jwt():
    """
    Generate a JWT for GitHub App authentication.
    """
    payload = {
        'iat': int(time.time()),
        'exp': int(time.time()) + 600,  # Token valid for 10 minutes
        'iss': GITHUB_APP_ID,
    }
    token = jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm='RS256')
    logging.info("Generated JWT for GitHub App.")
    return token

def get_installation_access_token():
    """
    Exchange the JWT for an installation access token.
    """
    jwt_token = get_jwt()
    installation_id = session.get('installation_id')  # Store the installation ID in the session

    if not installation_id:
        logging.error("Missing installation ID in session.")
        return None

    url = f'https://api.github.com/app/installations/{installation_id}/access_tokens'
    headers = {
        'Authorization': f'Bearer {jwt_token}',
        'Accept': 'application/vnd.github.v3+json',
    }

    response = requests.post(url, headers=headers)
    if response.status_code == 201:
        access_token = response.json().get('token')
        logging.info("Fetched GitHub App installation access token.")
        return access_token
    else:
        logging.error(f"Failed to get installation token: {response.status_code}")
        return None