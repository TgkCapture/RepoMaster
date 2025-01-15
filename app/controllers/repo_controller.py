"""repo_controller.py
"""
import requests
import logging
from flask import session
from app.controllers.auth_controller import get_installation_access_token

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