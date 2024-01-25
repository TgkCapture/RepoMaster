"""
github_controller.py
"""
import os
import requests
from flask import Blueprint, render_template

github_controller = Blueprint('github', __name__)

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

def get_github_repositories():
    url = f'https://api.github.com/users/{github_username}/repos'
    response = requests.get(url, timeout=60)
    if response.status_code == 200:
        return response.json()
    else:
        return None

@github_controller.route('/repositories')
def show_repositories():
    repositories = get_github_repositories()
    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to Fetch repo from Github"
