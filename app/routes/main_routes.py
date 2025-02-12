"""main_routes.py
"""
import os
import logging
import requests
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from app.controllers.auth_controller import get_installation_access_token, is_user_logged_in, get_jwt, clear_session
from app.controllers.issues_controller import get_github_issues, create_github_issue, close_github_issue
from app.controllers.repo_controller import get_github_repositories, delete_repository, get_branches, get_branch_details, create_branch, get_default_branch_sha, get_repository_contents, create_file, update_file, delete_file
from app.controllers.pull_requests_controller import get_pull_requests, create_pull_request, merge_pull_request, view_pull_request

main_routes = Blueprint('main', __name__)

@main_routes.route('/')
def home():
    """
    Renders the home page.
    """
    return render_template('index.html', is_user_logged_in=is_user_logged_in)

@main_routes.route('/logout')
def logout():
    """
    Route to log out the user.
    """
    clear_session()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('main.home'))

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

    username = session['github_username']  
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

@main_routes.route('/github/repository/<owner>/<repo_name>')
def show_repo_details(owner, repo_name):
    """
    Display repository details, including branches.
    """
    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to authenticate with GitHub.")
        return "Authentication failed", 500

    owner = session.get('github_username')

    branches = get_branches(owner=owner, repo_name=repo_name)
    
    if branches is not None:
        logging.info(f"Branches for repository '{repo_name}': {', '.join(branches)}")
        
        return render_template('repo_details.html',owner=owner, branches=branches, repo_name=repo_name)
    else:
        logging.error(f"Failed to fetch branches for repository '{repo_name}'.")
        return "Failed to fetch branches", 500

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
        repositories = get_github_repositories(session.get('github_username'), get_installation_access_token())
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
    - GET: Lists all pull requests, fetches details of a specific pull request, or renders the create form if `create` is requested.
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
        create_form = request.args.get('create')

        if pr_number:
            # Fetch details of the specific pull request
            pull_request = view_pull_request(session.get('github_username'), repo_name=repo_name, pr_number=int(pr_number))
            if pull_request:
                logging.info(f"Fetched details for pull request #{pr_number} in repository: {repo_name}")
                return render_template('pull_request_details.html', pull_request=pull_request, repo_name=repo_name)
            else:
                logging.error(f"Failed to fetch details for pull request #{pr_number} in repository: {repo_name}")
                return f"Failed to fetch details for pull request #{pr_number}", 500

        elif create_form:
            # Fetch branches and render the form for creating a pull request
            branches = get_branches(session.get('github_username'), repo_name=repo_name)  
            if branches is None:
                logging.error(f"Failed to fetch branches for repository {repo_name}.")
                return "Failed to fetch branches from GitHub", 500

            logging.info(f"Fetched {len(branches)} branches for repository: {repo_name}")
            return render_template('create_pull_request.html', repo_name=repo_name, branches=branches)

        else:
            # Fetch and display all pull requests
            pull_requests = get_pull_requests(session.get('github_username'), repo_name=repo_name)
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
            new_pr = create_pull_request(session.get('github_username'), repo_name=repo_name, title=title, body=body, head=head, base=base)
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
            merged_pr = merge_pull_request(session.get('github_username'), repo_name=repo_name, pr_number=int(pr_number))
            if merged_pr:
                logging.info(f"Pull request #{pr_number} successfully merged in repository {repo_name}.")
                return redirect(url_for('main.manage_pull_requests', repo_name=repo_name))
            else:
                return "Failed to merge pull request", 500

@main_routes.route('/repos/<owner>/<repo_name>/git/refs', methods=['GET', 'POST'])
def main_create_branch(owner, repo_name):
    """
    Render the branch creation form and handle branch creation in the repository.
    """
    if not is_user_logged_in():
        logging.warning("Unauthorized access attempt to create a branch.")
        return "You are not logged in", 403

    if request.method == 'GET':
        return render_template('create_branch.html', owner=owner, repo_name=repo_name)

    if request.method == 'POST':
        access_token = get_installation_access_token()
        if not access_token:
            logging.error("Failed to get access token for creating a branch.")
            flash("Failed to authenticate with GitHub.", "error")
            return redirect(request.url), 500

        ref_name = request.form.get("ref")  
        sha = request.form.get("sha") 

        if not ref_name:
            flash("Branch name is required.", "error")
            return redirect(request.url), 400

        if not sha:
            sha = get_default_branch_sha(owner, repo_name, access_token)
            if not sha:
                flash("Failed to retrieve default branch information.", "error")
                return redirect(request.url), 500

        branch = create_branch(owner, repo_name, access_token, ref_name, sha)
        if branch:
            logging.info(f"Successfully created branch '{ref_name}' in repository '{owner}/{repo_name}'.")
            flash(f"Branch '{ref_name}' successfully created.", "success")
            return redirect(url_for('main.show_branch_details', repo_name=repo_name, branch_name=ref_name))
        else:
            logging.error(f"Failed to create branch '{ref_name}' in repository '{owner}/{repo_name}'.")
            flash("Failed to create branch in the repository.", "error")
            return redirect(request.url), 500

@main_routes.route('/github/repository/branch-details')
def show_branch_details():
    """
    Display details of a specific branch.
    """
    if not is_user_logged_in():
        logging.warning("Unauthorized access attempt to fetch branch details.")
        return "You are not logged in", 403

    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to get access token for fetching branch details.")
        flash("Failed to authenticate with GitHub", "error")
        return "Failed to authenticate with GitHub", 500
        
    owner = session.get('github_username')  
    repo_name = request.args.get('repo_name')
    branch_name = request.args.get('branch_name')

    if not owner or not repo_name or not branch_name:
        logging.error("Missing required parameters.")
        return "Missing required parameters", 400

    branch_details, error = get_branch_details(owner, repo_name, branch_name)
    if error:
        return error, 500

    return render_template('branch_details.html', branch_details=branch_details, owner=owner, repo=repo_name, branch=branch_name)
    
@main_routes.route('/repos/<owner>/<repo_name>/branches/<branch_name>/delete', methods=['POST'])
def delete_branch(owner, repo_name, branch_name):
    access_token = get_installation_access_token()
    url = f'https://api.github.com/repos/{owner}/{repo_name}/git/refs/heads/{branch_name}'
    headers = {'Authorization': f'Bearer {access_token}'}

    response = requests.delete(url, headers=headers)
    if response.status_code == 204:
        flash(f"Branch '{branch_name}' successfully deleted.", "success")
    else:
        flash(f"Failed to delete branch '{branch_name}'.", "error")
    return redirect(url_for('main.show_repo_details', owner=owner, repo_name=repo_name))

@main_routes.route('/repos/<owner>/<repo_name>/branches/<branch_name>/rename', methods=['POST'])
def rename_branch(owner, repo_name, branch_name):
    access_token = get_installation_access_token()
    if not access_token:
        flash("Authentication failed.", "error")
        return redirect(url_for('main.show_branch_details', owner=owner, repo_name=repo_name, branch=branch_name))

    new_name = request.form.get('new_name')  
    if not new_name:
        flash("New branch name is required.", "error")
        return redirect(url_for('main.show_branch_details', owner=owner, repo_name=repo_name, branch=branch_name))

    url = f'https://api.github.com/repos/{owner}/{repo_name}/branches/{branch_name}/rename'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    payload = {'new_name': new_name}

    response = requests.post(url, json=payload, headers=headers)
    if response.status_code == 201:
        flash(f"Branch '{branch_name}' renamed to '{new_name}'.", "success")
        return redirect(url_for('main.show_repo_details', owner=owner, repo_name=repo_name))
    else:
        error_message = response.json().get('message', 'An error occurred.')
        flash(f"Failed to rename branch '{branch_name}': {error_message}", "error")
        return redirect(url_for('main.show_branch_details', owner=owner, repo_name=repo_name, branch=branch_name))

@main_routes.route('/github/repos/<owner>/<repo>/contents', methods=['GET'])
def get_contents(owner, repo):
    path = request.args.get('path', '')
    branch = request.args.get('branch')  
    access_token = get_installation_access_token()

    contents = get_repository_contents(owner, repo, path, branch)
    branches = get_branches(owner, repo)
    issues = get_github_issues(repo)
    pull_requests = get_pull_requests(owner, repo)

    return render_template(
        'contents.html',
        owner=owner,
        repo=repo,
        contents=contents,
        current_branch=branch,
        branches=branches,
        issues=issues,
        pull_requests=pull_requests
    )

@main_routes.route('/github/repos/<owner>/<repo>/contents', methods=['POST'])
def create_new_file(owner, repo):
    """
    Create a new file in the repository.
    """
    file_name = request.form.get('path')
    content = request.form.get('content')
    message = request.form.get('message', 'Add new file')

    result = create_file(owner, repo, file_name, content, message)
    if result:
        flash(f"File '{file_name}' created successfully", "success")
        return redirect(url_for('main.get_contents', owner=owner, repo=repo))
    else:
        flash("Failed to create file", "danger")
        return redirect(url_for('main.get_contents', owner=owner, repo=repo))

@main_routes.route('/github/repos/<owner>/<repo>/contents/<path:path>', methods=['POST'])
def update_existing_file(owner, repo, path): #TODO: Fix update file
    logging.debug(f"Received request to update file: owner={owner}, repo={repo}, path={path}")
    content = request.form.get('content')
    sha = request.form.get('sha')
    message = request.form.get('message', 'Update file')

    if not path:
        logging.error("Path parameter is missing")
        flash("Failed to update file: Path is missing", "danger")
        return redirect(url_for('main.get_contents', owner=owner, repo=repo))

    result = update_file(owner, repo, path, content, sha, message)
    if result:
        flash(f"File '{path}' updated successfully", "success")
        return redirect(url_for('main.get_contents', owner=owner, repo=repo))
    else:
        flash("Failed to update file", "danger")
        return redirect(url_for('main.get_contents', owner=owner, repo=repo))

@main_routes.route('/github/repos/<owner>/<repo>/contents/<path:path>', methods=['POST'])
def delete_existing_file(owner, repo, path):
    sha = request.form.get('sha')
    message = request.form.get('message', 'Delete file')

    if not sha:
        logging.warning("SHA not provided. Attempting to fetch SHA dynamically.")
        sha = fetch_file_sha(owner, repo, path)

    if not sha:
        flash("Failed to delete file: Unable to determine SHA", "danger")
        return redirect(url_for('main.get_contents', owner=owner, repo=repo))

    result = delete_file(owner, repo, path, sha, message)
    if result:
        flash(f"File '{path}' deleted successfully", "success")
    else:
        flash("Failed to delete file", "danger")
    
    return redirect(url_for('main.get_contents', owner=owner, repo=repo))