"""issues_controller.py
"""
import os
import requests
from flask import Blueprint

repo_controller = Blueprint('issues', __name__)

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

def get_github_issues(repo_name):
    """Fetches GitHub issues within a repo."""

    url = f'https://api.github.com/repos/{github_username}/{repo_name}/issues'

    response = requests.get(url, timeout=60)

    if response.status_code == 200:
        return response.json()
    else:
        return None