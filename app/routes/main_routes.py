"""main_routes.py
"""
import logging
import os
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.controllers.auth_controller import get_installation_access_token, is_user_logged_in, get_jwt
from app.controllers.github_controller import get_github_repositories
from app.controllers.issues_controller import get_github_issues, create_github_issue, close_github_issue
from app.controllers.repo_controller import delete_repository
from app.controllers.pull_requests_controller import get_pull_requests, create_pull_request, merge_pull_request, view_pull_request

main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def home():
    """
    Renders the home page.
    """
    return render_template('index.html', is_user_logged_in=is_user_logged_in)

@main_routes.route('/github/authorize', methods=['GET'])
def github_authorize():
    """
    Handle the GitHub App installation callback.
    """
    installation_id = request.args.get('installation_id')

    if not installation_id:
        logging.error("No installation ID provided in the request.")
        return "Installation ID is missing. Please install the GitHub App again.", 400

    session['installation_id'] = installation_id
    logging.info(f"Received installation ID: {installation_id}")

    access_token = get_installation_access_token()
    if access_token:
        logging.info("Installation access token successfully generated.")
        return redirect(url_for('main.home'))
    else:
        logging.error("Failed to generate installation access token.")
        return "Failed to complete installation process. Please try again.", 500

@main_routes.route('/github/install', methods=['GET'])
def install_github_app():
    """
    Redirect the user to the GitHub App installation page.
    """
    github_app_name = os.getenv("GITHUB_APP_NAME")  
    if not github_app_name:
        logging.error("GITHUB_APP_ID is not set in the environment.")
        return "Configuration error: GITHUB_APP_ID is not defined.", 500

    installation_url = f"https://github.com/apps/{github_app_name}/installations/new"
    return redirect(installation_url)

@main_routes.route('/github/repositories')
def show_github_repositories():
    """
    Display user's GitHub repositories.
    """
    if not is_user_logged_in():
        logging.warning("User attempted to access repositories without being logged in.")
        return "You are not logged in", 403

    username = "TgkCapture"  # TODO: Replace with a function to fetch the username 
    access_token = get_installation_access_token()

    if access_token:
        repositories = get_github_repositories(username, access_token)
        if repositories:
            logging.info(f"Fetched repositories for user: {username}, count: {len(repositories)}")
            return render_template('repositories.html', repositories=repositories)
        else:
            logging.error(f"Failed to fetch repositories for user: {username}")
            return "Failed to fetch repositories from GitHub", 500
    else:
        logging.error("Failed to get access token for GitHub repositories.")
        return "Failed to authenticate with GitHub", 500

@main_routes.route('/repositories/<repo_name>/issues', methods=['GET', 'POST'])
def manage_issues(repo_name):
    """
    Displays and manages issues for a specific repository. Allows viewing and creating or closing issues
    """
    if not is_user_logged_in():
        logging.warning("User attempted to access issues without being logged in.")
        return "You are not logged in", 403

    if request.method == 'GET':
        # Fetch and display issues
        issues = get_github_issues(repo_name)
        if issues is not None:
            logging.info(f"Fetched {len(issues)} issues for repository: {repo_name}")
            return render_template('issues.html', repo_name=repo_name, issues=issues)
        else:
            logging.error(f"Failed to fetch issues for repository: {repo_name}")
            return "Failed to fetch issues from GitHub", 500

    elif request.method == 'POST':
        if request.form.get('action') == 'close':
            # Close an existing issue
            issue_number = request.form.get('issue_number')
            if not issue_number:
                return "Issue number is required", 400
            closed_issue = close_github_issue(repo_name, issue_number)
            if closed_issue:
                logging.info(f"Issue #{issue_number} successfully closed in repository {repo_name}.")
                return redirect(url_for('main.manage_issues', repo_name=repo_name))
            else:
                return "Failed to close the issue", 500

        else:
            # Create a new issue
            title = request.form.get('title')
            body = request.form.get('body')
            if not title:
                return "Issue title is required", 400
            new_issue = create_github_issue(repo_name, title, body)
            if new_issue:
                logging.info(f"Issue created successfully in repository {repo_name}.")
                return redirect(url_for('main.manage_issues', repo_name=repo_name))

@main_routes.route('/delete_repo', methods=['GET', 'POST'])
def delete_repositories():
    """
    Displays repositories and allows deletion of selected ones.
    """
    if not is_user_logged_in():
        logging.warning("Unauthorized access to delete repositories.")
        return "You are not logged in", 403

    if request.method == 'GET':
        # Fetch and display repositories
        repositories = get_github_repositories("TgkCapture", get_installation_access_token()) #TODO: retrieve username dynamically
        if repositories:
            return render_template('delete_repo.html', repositories=repositories)
        else:
            return "Failed to fetch repositories", 500

    elif request.method == 'POST':
        # Delete selected repositories
        repos_to_delete = request.form.getlist('repo_to_delete[]')
        if not repos_to_delete:
            return "No repositories selected for deletion", 400

        result_message = delete_repository(repos_to_delete)
        logging.info(result_message)
        flash(result_message) 
        return redirect(url_for('main.delete_repositories'))

@main_routes.route('/repositories/<repo_name>/pull_requests', methods=['GET', 'POST'])
def manage_pull_requests(repo_name):
    """
    Handles pull requests for a repository:
    - GET: Lists all pull requests or fetches details of a specific pull request if 'pr_number' is provided.
    - POST: Allows creating or merging pull requests.
    """
    if not is_user_logged_in():
        logging.warning("User attempted to access pull requests without being logged in.")
        return "You are not logged in", 403

    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to get access token for managing pull requests.")
        return "Failed to authenticate with GitHub", 500

    if request.method == 'GET':
        # Check if a specific pull request is requested
        pr_number = request.args.get('pr_number')
        if pr_number:
            # Fetch details of the specific pull request
            pull_request = view_pull_request(owner="repo_owner", repo_name=repo_name, pull_number=int(pr_number))
            if pull_request:
                logging.info(f"Fetched details for pull request #{pr_number} in repository: {repo_name}")
                return render_template('pull_request_details.html', pull_request=pull_request, repo_name=repo_name)
            else:
                logging.error(f"Failed to fetch details for pull request #{pr_number} in repository: {repo_name}")
                return f"Failed to fetch details for pull request #{pr_number}", 500
        else:
            # Fetch and display all pull requests
            pull_requests = get_pull_requests(owner="repo_owner", repo_name=repo_name)
            if pull_requests is not None:
                logging.info(f"Fetched {len(pull_requests)} pull requests for repository: {repo_name}")
                return render_template('pull_requests.html', repo_name=repo_name, pull_requests=pull_requests)
            else:
                logging.error(f"Failed to fetch pull requests for repository: {repo_name}")
                return "Failed to fetch pull requests from GitHub", 500

    elif request.method == 'POST':
        action = request.form.get('action')

        if action == 'create':
            # Create a new pull request
            title = request.form.get('title')
            body = request.form.get('body')
            head = request.form.get('head')
            base = request.form.get('base')
            if not title or not head or not base:
                return "Title, head branch, and base branch are required to create a pull request", 400
            new_pr = create_pull_request(owner="repo_owner", repo_name=repo_name, title=title, body=body, head=head, base=base)
            if new_pr:
                logging.info(f"Pull request created successfully in repository {repo_name}.")
                return redirect(url_for('main.manage_pull_requests', repo_name=repo_name))
            else:
                return "Failed to create pull request", 500

        elif action == 'merge':
            # Merge an existing pull request
            pr_number = request.form.get('pr_number')
            if not pr_number:
                return "Pull request number is required to merge", 400
            merged_pr = merge_pull_request(owner="repo_owner", repo_name=repo_name, pull_number=int(pr_number), access_token=access_token)
            if merged_pr:
                logging.info(f"Pull request #{pr_number} successfully merged in repository {repo_name}.")
                return redirect(url_for('main.manage_pull_requests', repo_name=repo_name))
            else:
                return "Failed to merge pull request", 500
