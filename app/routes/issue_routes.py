"""issue_routes.py

Viewing, creating and closing issues.
"""
import logging
from flask import render_template, request, redirect, url_for
from app.routes import main_routes
from app.controllers.auth_controller import is_user_logged_in
from app.controllers.issues_controller import get_github_issues, create_github_issue, close_github_issue

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
