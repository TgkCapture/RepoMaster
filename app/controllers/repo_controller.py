"""repo_controller.py
"""
import requests
import logging
from flask import session
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token

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

def delete_repository(repos_to_delete):
    """Deletes GitHub repositories."""

    deleted_repos = []
    username = session.get("username", "TgkCapture")  
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot delete GitHub repositories.")
        return "Access token missing. Cannot delete repositories."

    for repo_name in repos_to_delete:
        delete_url = f'https://api.github.com/repos/{username}/{repo_name}'

        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/vnd.github.v3+json'
        }

        try:
            response = requests.delete(delete_url, headers=headers, timeout=60)
            response.raise_for_status()

            if response.status_code == 204:
                logging.info(f"Repository {repo_name} deleted successfully.")
                deleted_repos.append(repo_name)
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to delete repository {repo_name}: {e}")

    if deleted_repos:
        return f"Repositories '{', '.join(deleted_repos)}' deleted successfully"
    else:
        return "No repositories were deleted."

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

def create_branch(owner, repo, access_token, ref_name, sha):
    """
    Create a new branch in the specified repository.
    """
    url = f'https://api.github.com/repos/{owner}/{repo}/git/refs'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    payload = {
        "ref": f"refs/heads/{ref_name}",  
        "sha": sha
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()  
    except RequestException as e:
        logging.error(f"Failed to create branch '{ref_name}' in repository '{owner}/{repo}': {e}")
        return None

def get_default_branch_sha(owner, repo, access_token):
    url = f'https://api.github.com/repos/{owner}/{repo}'
    headers = {'Authorization': f'Bearer {access_token}'}
    
    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        repo_data = response.json()
        default_branch = repo_data['default_branch']

        branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{default_branch}'
        branch_response = requests.get(branch_url, headers=headers, timeout=60)
        branch_response.raise_for_status()
        branch_data = branch_response.json()
        return branch_data['object']['sha']
    except RequestException as e:
        logging.error(f"Failed to get default branch SHA for repository '{owner}/{repo}': {e}")
        return None

def get_branch_details(owner, repo_name, branch_name):
    """
    Fetch details about a specific branch in the repository.
    """
    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to authenticate with GitHub.")
        return None, "Authentication failed"

    url = f"https://api.github.com/repos/{owner}/{repo_name}/branches/{branch_name}"
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        branch_details = response.json()
        logging.info(f"Branch details fetched successfully: {branch_details}")
        return branch_details, None
    except RequestException as e:
        logging.error(f"Failed to fetch details for branch '{branch}' in repository '{owner}/{repo_name}': {e}")
        return None

def get_repository_contents(owner, repo, path=""):
    """
    Retrieve the contents of a file or directory.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch repository contents: {e}")
        return None

def create_file(owner, repo, path, content, message):
    """
    Add a new file to the repository.
    """
    url = f"{BASE_URL}/repos/{owner}/{repo}/contents/{path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {
        "message": message,
        "content": content  
    }

    try:
        response = requests.put(url, headers=headers, json=data, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to create file: {e}")
        return None