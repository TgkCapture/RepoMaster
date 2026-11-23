"""repo_routes.py

Repository listing, repository details and bulk deletion.
"""
import logging
from flask import render_template, request, redirect, url_for, session, flash
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, is_user_logged_in
from app.controllers.repo_controller import get_github_repositories, delete_repository, get_branches

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
