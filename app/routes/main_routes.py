"""main_routes.py
"""
from flask import Blueprint, render_template
from app.controllers.github_controller import get_github_repositories as github_repositories
# from app.controllers.repo_controller import show_issues
from app.controllers.main_controller import get_home_message, get_github_issues

main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def home():
    """Renders the home page.
    """
    message = get_home_message()
    return render_template('index.html', message=message)

@main_routes.route('/github/repositories')
def show_github_repositories():
    """Renders andd returns github repositories
    """
    repositories = github_repositories()
    if repositories:
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to Fetch repo from Github"

@main_routes.routes('/repositories/<repo_name>/issues')
def show_issues(repo_name):
    """Renders and returns github issues within a repo """

    issues = get_github_issues(repo_name)

    if issues:
        return render_template('issues.html', repo_name=repo_name, issues=issues)
    else:
        return f"Failed to fetch issues for {repo_name} from GitHub"

