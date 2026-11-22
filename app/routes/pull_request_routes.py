"""pull_request_routes.py

Listing, viewing, creating and merging pull requests.
"""
import logging
from flask import render_template, request, redirect, url_for, session
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, is_user_logged_in
from app.controllers.repo_controller import get_branches
from app.controllers.pull_requests_controller import get_pull_requests, create_pull_request, merge_pull_request, view_pull_request

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
