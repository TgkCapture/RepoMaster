import os
import requests
from app import app
from flask import render_template
from flask import request

github_username = os.environ.get('GITHUB_USERNAME')
github_token = os.environ.get('GITHUB_TOKEN')

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
                'Authorization': f'token {github_token}',
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


@app.route('/repositories/<owner>/<repo_name>/pulls')
def list_pull_requests(owner, repo_name):
    
    headers = {'Authorization': f'token {github_token}'}
    
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'
    response = requests.get(api_url, headers=headers)

    if response.status_code == 200:
        pull_requests = response.json()
        return render_template('pull_requests.html', pull_requests=pull_requests)
    else:
        return f"Failed to fetch pull requests: {response.status_code}"

@app.route('/repositories/<owner>/<repo_name>/pulls/<pull_number>')
def view_pull_request(owner, repo_name, pull_number):
    
    headers = {'Authorization': f'token {github_token}'}
    
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls/{pull_number}'
    response = requests.get(api_url, headers=headers)
    
    if response.status_code == 200:
        pull_request = response.json()
        return render_template('pull_request_details.html', pull_request=pull_request)
    else:
        return f"Failed to fetch pull request details: {response.status_code}"

@app.route('/repositories/<owner>/<repo_name>/pulls', methods=['POST'])
def create_pull_request(owner, repo_name):
    title = request.form.get('title')
    base = request.form.get('base')
    head = request.form.get('head')
    
    
    headers = {'Authorization': f'token {github_token}'}
    payload = {'title': title, 'base': base, 'head': head}
    
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/pulls'
    response = requests.post(api_url, headers=headers, json=payload)
    
    if response.status_code == 201:
        return "Pull request created successfully!"
    else:
        return f"Failed to create pull request: {response.status_code}"

