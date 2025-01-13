"""main_routes.py
"""
import logging
from flask import Blueprint, render_template, request, redirect, url_for, session
from app.controllers.github_controller import get_github_repositories as github_repositories
from app.controllers.repo_controller import delete_repository
from app.controllers.pull_requests_controller import view_pull_request, create_pull_request, get_pull_requests
from app.controllers.main_controller import get_home_message
from app.controllers.issues_controller import get_github_issues
from app.controllers.auth_controller import get_installation_access_token, is_user_logged_in
from jose import jwt
# from app.config.oauth_config import github

main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def home():
    """Renders the home page.
    """
    return render_template('index.html', is_user_logged_in=is_user_logged_in)

@main_routes.route('/github/repositories')
def show_github_repositories():
    username = None
    access_token = None

    if is_user_logged_in():
        username, _ = get_user_info()  # Fetch username
        access_token = get_installation_access_token()  # Get GitHub App installation token

        if username:
            logging.info(f"Logged in as GitHub user: {username}")
        if access_token:
            logging.info("Fetched GitHub App installation token successfully.")
    else:
        logging.warning("User attempted to access repositories without being logged in.")
        return "You are not logged in"

    repositories = get_github_repositories(username, access_token)

    if repositories:
        logging.info(f"Fetched repositories for user: {username}, count: {len(repositories)}")
        return render_template('repositories.html', repositories=repositories)
    else:
        logging.error(f"Failed to fetch repositories for user: {username}")
        return "Failed to fetch repositories from GitHub"

@main_routes.route('/github/callback', methods=['GET'])
def github_callback():
    """Handles the GitHub App callback after authentication or app setup."""  

    # Retrieve the code and state from the GitHub callback URL
    code = request.args.get('code')
    state = request.args.get('state')

    if not code:
        logging.error("GitHub callback missing 'code' parameter.")
        return "GitHub authentication failed. 'code' not provided.", 400

    try:
        # Exchange the code for an access token (GitHub App installation flow)
        token_response = github.authorized_response()

        if not token_response or 'access_token' not in token_response:
            logging.error("GitHub token exchange failed.")
            return "GitHub token exchange failed.", 400

        # Save the access token in the session (or database for production)
        session['github_token'] = token_response['access_token']
        logging.info(f"GitHub access token: {token_response['access_token'][:6]}******")

        # Redirect to the homepage or another appropriate route
        return redirect(url_for('main.home'))

    except Exception as e:
        logging.error(f"Error during GitHub callback handling: {str(e)}")
        return f"GitHub callback handling failed: {str(e)}", 500

        


@main_routes.route('/repositories/<repo_name>/issues')
def show_issues(repo_name):
    """Renders and returns github issues within a repo """

    issues = get_github_issues(repo_name)

    if issues:
        return render_template('issues.html', repo_name=repo_name, issues=issues)
    else:
        return f"Failed to fetch issues for {repo_name} from GitHub"

@main_routes.route('/repositories/<owner>/<repo_name>/pulls')
def list_pull_requests(owner, repo_name):
    """Renders and returns pull requests for a GitHub repository."""

    pull_requests = get_pull_requests(owner, repo_name)

    if pull_requests:
        return render_template('pull_requests.html', pull_requests=pull_requests)
    else:
        return f"Failed to fetch pull requests for {owner}/{repo_name} from GitHub"

@main_routes.route('/delete_repo', methods=['GET', 'POST'])
def delete_repo():
    """Deletes GitHub repositories."""

    if request.method == 'POST':
        repos_to_delete = request.form.getlist('repo_to_delete[]')
        message = delete_repository(repos_to_delete)
        return message
    else:
        repositories = github_repositories()
        if repositories:
            return render_template('delete_repo.html', repositories=repositories)
        else:
            return "Failed to Fetch Repos from Github"

@main_routes.route('/repositories/<owner>/<repo_name>/pulls/<pull_number>')
def view_pull_request_route(owner, repo_name, pull_number):
    """Renders details for a GitHub pull request."""

    pull_request = view_pull_request(owner, repo_name, pull_number)

    if pull_request:
        return render_template('pull_request_details.html', pull_request=pull_request)
    else:
        return f"Failed to fetch pull request details"

@main_routes.route('/repositories/<owner>/<repo_name>/pulls', methods=['POST'])
def create_pull_request_route(owner, repo_name):
    """Creates a new GitHub pull request."""

    title = request.form.get('title')
    base = request.form.get('base')
    head = request.form.get('head')

    message = create_pull_request(owner, repo_name, title, base, head)
    return message