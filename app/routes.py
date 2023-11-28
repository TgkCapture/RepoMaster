import os
import requests
from app import app
from flask import render_template

github_username = os.environ.get('GITHUB_USERNAME')

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

@app.route('/issues/<repo_name>')
def show_issues(repo_name):
    
    issues = [
        {'title': 'Issue 1', 'description': 'First issue'},
        {'title': 'Issue 2', 'description': 'Second issue'}
        
    ]
    return render_template('issues.html', repo_name=repo_name, issues=issues)

@app.route('/delete_repo')
def delete_repository():
    
    repositories = [
        {'name': 'Repo 1', 'description': 'First repository'},
        {'name': 'Repo 2', 'description': 'Second repository'}
        
    ]
    return render_template('delete_repo.html', repositories=repositories)

