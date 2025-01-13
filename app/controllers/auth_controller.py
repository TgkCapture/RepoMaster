"""auth_controller.py
"""

import requests
import logging
import time
from flask import Blueprint, session, request, redirect, url_for
from app.config.github_app_config import GITHUB_APP_ID, GITHUB_PRIVATE_KEY
from jose import jwt

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
        'Accept': 'application/vnd.github+json',
    }

    response = requests.post(url, headers=headers)
    if response.status_code == 201:
        access_token = response.json().get('token')
        logging.info("Fetched GitHub App installation access token.")
        session['github_installation_token'] = access_token  # Store in session
        return access_token
    else:
        logging.error(f"Failed to get installation token: {response.status_code}")
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

@auth_controller.route('/github/authorize', methods=['GET'])
def authorize_github_app():
    """
    Handle the GitHub App installation callback.
    """
    # Extract installation_id from the query parameters
    installation_id = request.args.get('installation_id')

    if not installation_id:
        logging.error("No installation ID provided in the request.")
        return "Installation ID is missing. Please install the GitHub App.", 400

    # Store the installation ID in the session
    session['installation_id'] = installation_id
    logging.info(f"Received installation ID: {installation_id}")

    # Generate the installation access token
    access_token = get_installation_access_token()
    if access_token:
        logging.info("Installation access token successfully generated.")
        return redirect(url_for('main.home'))  # Redirect to the home page or a relevant route
    else:
        logging.error("Failed to generate installation access token.")
        return "Failed to complete installation process. Please try again.", 500

@auth_controller.route('/github/install', methods=['GET'])
def install_github_app():
    """
    Redirect the user to the GitHub App installation page.
    """
    installation_url = f"https://github.com/apps/{GITHUB_APP_ID}/installations/new"
    return redirect(installation_url)
