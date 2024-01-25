"""repo_controller.py
"""
import os
import requests
from flask import Blueprint

repo_controller = Blueprint('repo', __name__)

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

def delete_repository(repos_to_delete):
    """Deletes GitHub repositories."""

    deleted_repos = []

    for repo_name in repos_to_delete:
        delete_url = f'https://api.github.com/repos/{github_username}/{repo_name}'

        headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }

        try:
            response = requests.delete(delete_url, headers=headers, timeout=60)
            response.raise_for_status()

            if response.status_code == 204:
                deleted_repos.append(repo_name)
        except requests.exceptions.RequestException as e:
            print(f"Failed to delete repository {github_username}/{repo_name}: {e}")

    if deleted_repos:
        return f"Repositories '{', '.join(deleted_repos)}' deleted successfully"
    else:
        return "No Repos were Deleted"

