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

def view_pull_request(owner, repo_name, pull_number):
    """Fetches details for a GitHub pull request."""

    headers = {'Authorization': f'token {github_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls/{pull_number}'

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        if response.status_code == 200:
            return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch pull request details: {e}")

    return None

def create_pull_request(owner, repo_name, title, base, head):
    """Creates a new GitHub pull request."""

    headers = {'Authorization': f'token {github_token}'}
    payload = {'title': title, 'base': base, 'head': head}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()

        if response.status_code == 201:
            return "Pull request created successfully!"
    except requests.exceptions.RequestException as e:
        print(f"Failed to create pull request: {e}")

    return f"Failed to create pull request: {response.status_code}"