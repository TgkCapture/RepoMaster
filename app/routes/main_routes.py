"""main_routes.py
"""
from flask import Blueprint, render_template, request
from app.controllers.github_controller import get_github_repositories as github_repositories
from app.controllers.repo_controller import delete_repository
from app.controllers.pull_requests_controller import view_pull_request, create_pull_request, get_pull_requests
from app.controllers.main_controller import get_home_message
from app.controllers.issues_controller import get_github_issues
from app.controllers.auth_controller import github_login
from dotenv import load_dotenv
import os
# from app.controllers.auth_controller import fetch_github_repositories

# Load environment variables
load_dotenv()

# GitHub OAuth Configuration
CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"


main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def home():
    """Renders the home page.
    """
    message = get_home_message()
    return render_template('index.html', message=message)

@main_routes.route('/login')
def login():
    """Redirects to GitHub Login"""
    return github_login()

@main_routes.route('/callback')
def github_callback():
    """Handles GitHub OAuth callback and exchanges code for access token"""
    code = request.args.get("code")  # Get the `code` from the query parameters

    if not code:
        return "Authorization failed. No code received.", 400

    # Exchange the code for an access token
    token_response = requests.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
        },
    )

    token_json = token_response.json()
    access_token = token_json.get("access_token")

    if not access_token:
        return f"Failed to retrieve access token: {token_json.get('error_description', 'Unknown error')}", 400

    # Save the token in the session
    session["github_token"] = access_token
    return redirect(url_for("main_routes.show_github_repositories"))

@main_routes.route('/github/repositories')
def show_github_repositories():
    """Fetches and displays GitHub repositories"""
    repositories, error = github_repositories()

    if error:
        return error, 400

    return render_template("repositories.html", repositories=repositories)

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