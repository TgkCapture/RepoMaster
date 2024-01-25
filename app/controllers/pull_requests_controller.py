"""pull_requests_controller.py
"""
import os
import requests
from flask import Blueprint

repo_controller = Blueprint('pull_requests', __name__)

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

def get_pull_requests(owner, repo_name):
    """Lists all pull requests for a repository"""

    headers = {'Authorization': f'token {github_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = requests.get(api_url, headers=headers, timeout=60)
        response.raise_for_status()

        return response.json()
    except requests.exceptions.RequestException as e:

        print(f"Failed to fetch pull requests: {e}")
        return None