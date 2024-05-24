"""pull_requests_controller.py
"""
import requests
import logging
from flask import Blueprint

repo_controller = Blueprint('pull_requests', __name__)

def get_pull_requests(owner, repo_name, access_token):
    """Lists all pull requests for a repository"""

    headers = {'Authorization': f'token {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = requests.get(api_url, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error occurred: {req_err}")
    return None


def view_pull_request(owner, repo_name, pull_number, access_token):
    """Fetches details for a GitHub pull request."""
    headers = {'Authorization': f'token {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls/{pull_number}'

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        if response.status_code == 200:
            return response.json()
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred while fetching pull request {owner}/{repo_name}#{pull_number}: {http_err}")
    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error occurred while fetching pull request {owner}/{repo_name}#{pull_number}: {req_err}")

    return None

def create_pull_request(owner, repo_name, title, base, head, access_token):
    """Creates a new GitHub pull request."""
    headers = {'Authorization': f'token {access_token}'}
    payload = {'title': title, 'base': base, 'head': head}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()

        if response.status_code == 201:
            logging.info(f"Pull request created successfully for {owner}/{repo_name}")
            return "Pull request created successfully!"
        else:
            logging.error(f"Unexpected response status code: {response.status_code}")
            return f"Unexpected response status code: {response.status_code}"
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred while creating pull request: {http_err}")
        return f"HTTP error occurred: {http_err}"
    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error occurred while creating pull request: {req_err}")
        return f"Request error occurred: {req_err}"