"""repo_controller.py
"""
import requests
import logging
from flask import session
from .auth import get_installation_access_token

def delete_repository(repos_to_delete):
    """
    Deletes GitHub repositories.

    Args:
        repos_to_delete (list): A list of repository names to delete.

    Returns:
        str: A message indicating which repositories were deleted successfully, or an error message.
    """
    access_token = get_installation_access_token() 
    if not access_token:
        logging.error("Access token is missing. Cannot delete GitHub repositories.")
        return "Failed to retrieve access token. Cannot proceed with deletion."

    github_username = session.get("username", "TgkCapture")  # Default fallback username
    deleted_repos = []

    for repo_name in repos_to_delete:
        delete_url = f'https://api.github.com/repos/{github_username}/{repo_name}'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/vnd.github.v3+json'
        }

        try:
            response = requests.delete(delete_url, headers=headers, timeout=60)
            response.raise_for_status()

            if response.status_code == 204:  # No content (successful deletion)
                logging.info(f"Repository '{github_username}/{repo_name}' deleted successfully.")
                deleted_repos.append(repo_name)
            else:
                logging.warning(f"Unexpected response while deleting repository '{repo_name}': {response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.error(f"Failed to delete repository '{repo_name}': {e}")

    if deleted_repos:
        return f"Repositories '{', '.join(deleted_repos)}' deleted successfully."
    else:
        return "No repositories were deleted. Please check the repository names and try again."

