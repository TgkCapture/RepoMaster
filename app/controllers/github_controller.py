# github_controller.py
import requests
from flask import Blueprint, render_template, request

github_controller = Blueprint('github', __name__)

def get_github_repositories():
    url = f'https://api.github.com/users/{github_username}/repos'
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        return None

@github_controller.route('/repositories')
def show_repositories():
    repositories = get_github_repositories()
    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to Fetch repo from Github"
