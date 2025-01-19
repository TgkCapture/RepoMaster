"""
github_controller.py
"""
import os
import requests
import logging
from flask import Blueprint, request
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token

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

def get_branches(owner, repo_name):
    """Fetches all branches of a repository."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch branches.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/branches'

    try:
        response = requests.get(api_url, headers=headers, timeout=60)
        response.raise_for_status()
        branches = response.json()
        return [branch['name'] for branch in branches]
    except RequestException as e:
        logging.error(f"Failed to fetch branches for repository {repo_name}: {e}")
        return None
