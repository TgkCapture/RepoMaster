# main_routes.py
from flask import Blueprint, render_template
from app.controllers.github_controller import get_github_repositories as github_repositories
from app.controllers.repo_controller import get_github_repositories as repo_repositories
from app.controllers.main_controller import get_home_message

main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def home():
    message = get_home_message()
    return render_template('home.html', message=message)

@main_routes.route('/github/repositories')
def show_github_repositories():
    repositories = github_repositories()
    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to Fetch repo from Github"

@main_routes.route('/repo/repositories')
def show_repo_repositories():
    repositories = repo_repositories()
    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to Fetch repo from Github"

# Add other routes as needed
