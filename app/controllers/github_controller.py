"""
github_controller.py
"""
import os
import requests
import logging
from flask import Blueprint, render_template, request, redirect, url_for
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

        if not response.headers.get('Authorization'):
            logging.error(f"Missing access token in request for user: {username}")
            return None

        if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) <= 5:
            logging.warning("Approaching GitHub API rate limit, consider adding retries")

        repositories = response.json()
        return repositories

    except RequestException as e:
        if e.args[0].startswith('401 Client Error: Unauthorized'):
            logging.error(f"Failed to fetch repositories: Potential expired token for user: {username}")
            # Redirect user to re-authentication flow
            return None
        else:
            logging.error(f"Failed to fetch repositories: {e}")
            return None

@github_controller.route('/repositories')
def show_repositories():
    username, access_token = None, None

    if is_user_logged_in(): 
        username, _ = get_user_info()
        access_token = get_github_oauth_token()
         
    repositories = get_github_repositories(username, access_token)
    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return render_template('error.html', error_message="Failed to fetch repositories")
