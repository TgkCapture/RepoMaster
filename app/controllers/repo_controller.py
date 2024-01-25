"""repo_controller.py
"""
import os
import requests
from flask import Blueprint, render_template, request
from app.controllers.github_controller import get_github_repositories

repo_controller = Blueprint('repo', __name__)

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

@repo_controller.route('/repositories/<repo_name>/issues')
def show_issues(repo_name):

    url = f'https://api.github.com/repos/{github_username}/{repo_name}/issues'

    response = requests.get(url, timeout=60)
    if response.status_code == 200:
        issues = response.json()
        return render_template('issues.html', repo_name=repo_name, issues=issues)
    else:
        return f"Failed to fetch issues for {repo_name} from GitHub API"

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

@repo_controller.route('/repositories/<owner>/<repo_name>/pulls')
def list_pull_requests(owner, repo_name):

    headers = {'Authorization': f'token {github_token}'}

    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'
    response = requests.get(api_url, headers=headers, timeout=60)

    if response.status_code == 200:
        pull_requests = response.json()
        return render_template('pull_requests.html', pull_requests=pull_requests)
    else:
        return f"Failed to fetch pull requests: {response.status_code}"
