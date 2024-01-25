"""repo_controller.py
"""
import os
import requests
from flask import Blueprint, render_template, request
from app.controllers.github_controller import get_github_repositories

repo_controller = Blueprint('repo', __name__)

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

@repo_controller.route('/delete_repo', methods=['GET', 'POST'])
def delete_repository():
    if request.method == 'POST':
        repos_to_delete = request.form.getlist('repo_to_delete[]')
        deleted_repos = []

        for repo_name in repos_to_delete:
            delete_url = f'https://api.github.com/repos/{github_username}/{repo_name}'

            headers = {
                'Authorization': f'token {github_token}',
                'Accept': 'application/vnd.github.v3+json'
            }

            response = requests.delete(delete_url, headers=headers, timeout=60)

            if response.status_code == 204:
                deleted_repos.append(repo_name)

        if deleted_repos:
            message = f"Repositories '{', '.join(deleted_repos)}' deleted successfully"
        else:
            message = "No Repos were Deleted"

        return message
    else:
        repositories = get_github_repositories()
        if repositories:
            return render_template('delete_repo.html', repositories=repositories)
        else:
            return "Failed to Fetch Repos from Github"

