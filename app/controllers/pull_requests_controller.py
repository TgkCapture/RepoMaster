"""pull_requests_controller.py
"""
import logging
import requests
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token

def get_pull_requests(owner, repo_name):
    """Lists all pull requests for a repository."""
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

def create_pull_request(owner, repo_name, title, body, base, head):
    """Creates a new GitHub pull request."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot create pull request.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    payload = {'title': title, 'body': body, 'base': base, 'head': head}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'

    logging.debug(f"Payload for creating PR: {payload}")

    try:
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        pull = response.json()
        logging.info(f"Pull request created successfully in repository {repo_name}.")
        return pull
    except requests.exceptions.RequestException as e:
        if e.response:
            logging.error(f"Failed to create pull request: {e.response.json()}")
        else:
            logging.error(f"Failed to create pull request: {e}")
        return None

def merge_pull_request(owner, repo_name, pr_number):
    """Merges a pull request in a repository."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot merge pull request.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls/{pr_number}/merge'

    try:
        response = requests.put(api_url, headers=headers, timeout=60)
        if response.status_code == 409:
            logging.error(f"Merge conflict for pull request #{pr_number} in repository {repo_name}.")
            return {"error": "Merge conflict"}

        response.raise_for_status()
        merge_result = response.json()
        logging.info(f"Pull request #{pr_number} successfully merged in repository {repo_name}.")
        return merge_result
    except RequestException as e:
        logging.error(f"Failed to merge pull request #{pr_number}: {e}")
        return None
