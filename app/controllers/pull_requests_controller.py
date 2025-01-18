"""pull_requests_controller.py
"""
import os
import logging
import requests
from flask import Blueprint, session
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token

repo_controller = Blueprint('pull_requests', __name__)

def get_pull_requests(owner, repo_name):
    """Lists all pull requests for a repository"""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch pull requests.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = requests.get(api_url, headers=headers, timeout=60)
        response.raise_for_status()

        pulls = response.json()
        logging.info(f"Fetched {len(pulls)} pull requests for repository {repo_name}.")
        return pulls
    except RequestException as e:
        logging.error(f"Failed to fetch pull requests for repository {repo_name}: {e}")
        return None

def view_pull_request(owner, repo_name, pull_number):
    """Fetches details for a GitHub pull request."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch pull request details.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls/{pull_number}'

    try:
        response = requests.get(api_url, headers=headers, timeout=60)
        response.raise_for_status()

        pull = response.json()
        logging.info(f"Fetched pull request #{pull_number} for repository {repo_name}.")
        return pull
    except RequestException as e:
        logging.error(f"Failed to fetch pull request details: {e}")
        return None

def create_pull_request(owner, repo_name, title, base, head):
    """Creates a new GitHub pull request."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot create pull request.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    payload = {'title': title, 'base': base, 'head': head}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        pull = response.json()
        logging.info(f"Pull request created successfully in repository {repo_name}.")
        return pull
    except RequestException as e:
        logging.error(f"Failed to create pull request: {e}")
        return None
