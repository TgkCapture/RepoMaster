import os
import requests
from app import app
from flask import render_template
from flask import request

github_username = os.environ.get('GITHUB_USERNAME')
# TODO: retrive github token

@app.route('/')
def index():
    return 'Welcome to RepoMaster!'

def get_github_repositories():
    url = f'https://api.github.com/users/{github_username}/repos'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        return None

@app.route('/repositories')
def show_repositories():

    repositories = get_github_repositories()

    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to Fetch repo from Github"

@app.route('/repositories/<repo_name>/issues')
def show_issues(repo_name):
    
    url = f'https://api.github.com/repos/{github_username}/{repo_name}/issues'

    response = requests.get(url)
    if response.status_code == 200:
        issues = response.json()
        return render_template('issues.html', repo_name=repo_name, issues=issues)
    else:
        return f"Failed to fetch issues for {repo_name} from GitHub API"


@app.route('/delete_repo', methods=['GET', 'POST'])
def delete_repository():
    if request.method == 'POST':
        repos_to_delete = request.form.getlist('repo_to_delete[]')
        deleted_repos = []

        for repo_name in repos_to_delete:
            delete_url = f'https://api.github.com/repos/{github_username}/{repo_name}'

            headers = {
                'Authorization': f'token {GITHUB_TOKEN}',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            response = requests.delete(delete_url, headers=headers)

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

