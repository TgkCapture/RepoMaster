"""
github_controller.py
"""
import requests
import logging
from flask import Blueprint, render_template, redirect, url_for
from app.controllers.auth_controller import get_github_oauth_token, get_user_info, is_user_logged_in
from requests.exceptions import RequestException

github_controller = Blueprint('github', __name__)

def get_github_repositories(username, access_token):
    """
    Fetches all repository URLs for a given user using the GitHub API.
    """
    url = f'https://api.github.com/users/{username}/repos'
    headers = {'Authorization': f'token {access_token}'} if access_token else None

    logging.debug(f"Fetching repositories for user: {username}")

    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()

        repositories = response.json()
        logging.info(f"Fetched {len(repositories)} repositories for user: {username}")
        return repositories

    except RequestException as e:
        logging.error(f"Failed to fetch repositories: {e}")
        return None

@github_controller.route('/repositories')
def show_repositories():
    if not is_user_logged_in():
        logging.warning("User is not logged in. Redirecting to login page.")
        return redirect(url_for('main.login_route'))

    username, _ = get_user_info()
    access_token = get_github_oauth_token()

    if not username or not access_token:
        error_message = "Failed to retrieve user information. Please log in again."
        logging.error(error_message)
        return render_template('error.html', error_message=error_message)

    repositories = get_github_repositories(username, access_token)
    if repositories is not None:
        return render_template('repositories.html', repositories=repositories)
    else:
        error_message = "Failed to fetch repositories. Please try again later."
        return render_template('error.html', error_message=error_message)
