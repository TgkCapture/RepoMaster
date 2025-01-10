"""
github_controller.py
"""
import os
import requests
import logging
from flask import Blueprint, render_template, request, redirect, url_for, session
from app.controllers.auth_controller import get_github_oauth_token, get_user_info, is_user_logged_in
from requests.exceptions import RequestException 

github_controller = Blueprint('github', __name__)


def get_github_repositories(username, access_token):
    url = f'https://api.github.com/users/{username}/repos'
    headers = {'Authorization': f'token {access_token}'} if access_token else None

    logging.debug(f"Fetching repositories for user: {username}")

    try:
        # Make the API call and assign the response to the 'response' variable
        response = requests.get(url, headers=headers, timeout=60)
        
        # Check if the request was successful (status code 200)
        response.raise_for_status()

        # Check the rate limit headers
        if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) <= 5:
            logging.warning("Approaching GitHub API rate limit, consider adding retries")

        # Parse the response as JSON
        repositories = response.json()

        # Check if repositories were returned
        if repositories:
            logging.info(f"Fetched repositories for user: {username}, count: {len(repositories)}")
            return repositories
        else:
            logging.error(f"No repositories found for user: {username}")
            return None

    except requests.exceptions.RequestException as e:
        # Handle request errors (like 401 Unauthorized or other issues)
        if isinstance(e, requests.exceptions.HTTPError) and e.response.status_code == 401:
            logging.error(f"Failed to fetch repositories: Potential expired token for user: {username}")
        else:
            logging.error(f"Failed to fetch repositories: {e}")
        return None

        if e.args[0].startswith('401 Client Error: Unauthorized'):
            logging.error(f"Failed to fetch repositories: Potential expired token for user: {username}")
            # Clear session token and redirect to login to refresh the token
            session.pop('github_token', None)  # Remove expired token
            return redirect(url_for('main.login_route'))  # Redirect to re-authentication flow
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
