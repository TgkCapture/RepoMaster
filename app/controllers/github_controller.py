"""
github_controller.py
"""
import os
import requests
from flask import Blueprint, render_template, request
from app.controllers.auth_controller import get_github_oauth_token, get_user_info, is_user_logged_in

github_controller = Blueprint('github', __name__)


def get_github_repositories(username, access_token):
    url = f'https://api.github.com/users/{username}/repos'
    headers = {'Authorization': f'token {access_token}'} if access_token else None
    response = requests.get(url, headers=headers, timeout=60)
    if response.status_code == 200:
        return response.json()
    else:
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
