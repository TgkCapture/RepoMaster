"""
github_controller.py
"""
import os
import requests
import logging
from flask import Blueprint, render_template, request, redirect, url_for, session
from requests.exceptions import RequestException

github_controller = Blueprint('github', __name__)

def get_github_repositories(username, access_token):
    url = f'https://api.github.com/users/{username}/repos'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        repositories = response.json()
        return repositories
    except RequestException as e:
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
