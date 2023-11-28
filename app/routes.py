from app import app
from flask import render_template

@app.route('/')
def index():
    return 'Welcome to RepoMaster!'

@app.route('/repositories')
def show_repositories():

    repositories = [
        {'name': 'Repo 1', 'description': 'First repository'},
        {'name': 'Repo 2', 'description': 'Second repository'}
    ]

    return render_template('repositories.html', repositories=repositories)

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

