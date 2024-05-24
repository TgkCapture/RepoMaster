"""
main_routes.py
"""
import logging
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session
from app.controllers.github_controller import get_github_repositories
from app.controllers.repo_controller import delete_repository
from app.controllers.pull_requests_controller import view_pull_request, create_pull_request, get_pull_requests
from app.controllers.issues_controller import get_github_issues
from app.controllers.auth_controller import login, logout, authorized, github, get_github_oauth_token, is_user_logged_in, get_user_info

main_routes = Blueprint('main', __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_user_logged_in():
            return redirect(url_for('main.login_route'))
        return f(*args, **kwargs)
    return decorated_function

@main_routes.route('/')
def home():
    """Renders the home page."""
    return render_template('index.html', get_github_oauth_token=get_github_oauth_token)

@main_routes.route('/login')
def login_route():
    """Renders the login Page."""
    return login()

@main_routes.route('/logout')
def logout_route():
    """Logs out the user."""
    return logout()

@main_routes.route('/github/callback')
def authorized_route():
    """Handles the callback from GitHub OAuth."""
    return authorized()

@github.tokengetter
def get_github_oauth_token_route():
    return get_github_oauth_token()

@main_routes.route('/github/repositories')
@login_required
def show_github_repositories():
    """Renders and returns GitHub repositories."""
    username, _ = get_user_info()
    access_token = get_github_oauth_token()
    
    repositories = get_github_repositories(username, access_token)
    if repositories:
        logging.info(f"Fetched repositories for user: {username}, count: {len(repositories)}")
        return render_template('repositories.html', repositories=repositories)
    else:
        return "Failed to fetch repositories from GitHub."

@main_routes.route('/repositories/<repo_name>/issues')
@login_required
def show_issues(repo_name):
    """Renders and returns GitHub issues within a repo."""
    access_token = get_github_oauth_token()
    issues = get_github_issues(repo_name, access_token)
    
    if issues:
        return render_template('issues.html', repo_name=repo_name, issues=issues)
    else:
        return f"Failed to fetch issues for {repo_name} from GitHub"

@main_routes.route('/repositories/<owner>/<repo_name>/pulls')
@login_required
def list_pull_requests(owner, repo_name):
    """Renders and returns pull requests for a GitHub repository."""
    access_token = get_github_oauth_token()
    pull_requests = get_pull_requests(owner, repo_name, access_token)
    
    if pull_requests:
        return render_template('pull_requests.html', pull_requests=pull_requests)
    else:
        logging.error(f"Failed to fetch pull requests for {owner}/{repo_name} from GitHub.")
        return render_template('error.html', error_message=f"Failed to fetch pull requests for {owner}/{repo_name} from GitHub.")

@main_routes.route('/delete_repo', methods=['GET', 'POST'])
@login_required
def delete_repo():
    """Deletes GitHub repositories."""
    access_token = get_github_oauth_token()
    if request.method == 'POST':
        repos_to_delete = request.form.getlist('repo_to_delete[]')
        message = delete_repository(repos_to_delete, access_token)
        return message
    else:
        username, _ = get_user_info()
        repositories = get_github_repositories(username, access_token)
        if repositories:
            return render_template('delete_repo.html', repositories=repositories)
        else:
            return "Failed to fetch repositories from GitHub"

@main_routes.route('/repositories/<owner>/<repo_name>/pulls/<pull_number>')
@login_required
def view_pull_request_route(owner, repo_name, pull_number):
    """Renders details for a GitHub pull request."""
    access_token = get_github_oauth_token()
    pull_request = view_pull_request(owner, repo_name, pull_number, access_token)
    
    if pull_request:
        return render_template('pull_request_details.html', pull_request=pull_request)
    else:
        logging.error(f"Failed to fetch pull request details for {owner}/{repo_name}#{pull_number}.")
        return render_template('error.html', error_message=f"Failed to fetch pull request details for {owner}/{repo_name}#{pull_number}.")

@main_routes.route('/repositories/<owner>/<repo_name>/pulls', methods=['POST'])
@login_required
def create_pull_request_route(owner, repo_name):
    """Creates a new GitHub pull request."""
    access_token = get_github_oauth_token()
    title = request.form.get('title')
    base = request.form.get('base')
    head = request.form.get('head')
    
    message = create_pull_request(owner, repo_name, title, base, head, access_token)
    
    if "successfully" in message.lower():
        return render_template('success.html', message=message)
    else:
        logging.error(f"Failed to create pull request for {owner}/{repo_name}")
        return render_template('error.html', error_message=message)