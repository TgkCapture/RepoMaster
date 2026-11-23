"""repo_routes.py

Repository listing, repository details and bulk deletion.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import get_github_repositories, delete_repository, get_branches

@main_routes.route('/github/repositories')
@login_required
def show_github_repositories():
    """
    Display the repositories the GitHub App installation can access.
    """
    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to get access token for GitHub repositories.")
        return "Failed to authenticate with GitHub", 500

    repositories = get_github_repositories(access_token)
    if repositories is None:
        logging.error("Failed to fetch repositories for the installation.")
        return "Failed to fetch repositories from GitHub", 500

    logging.info(f"Fetched {len(repositories)} repositories for the installation.")
    return render_template('repositories.html', repositories=repositories)

@main_routes.route('/github/repository/<owner>/<repo_name>')
@login_required
def show_repo_details(owner, repo_name):
    """
    Display repository details, including branches.
    """
    branches = get_branches(owner=owner, repo_name=repo_name)

    if branches is None:
        logging.error(f"Failed to fetch branches for repository '{owner}/{repo_name}'.")
        return "Failed to fetch branches", 500

    logging.info(f"Branches for repository '{owner}/{repo_name}': {', '.join(branches)}")
    return render_template('repo_details.html', owner=owner, branches=branches, repo_name=repo_name)

@main_routes.route('/delete_repo', methods=['GET', 'POST'])
@login_required
def delete_repositories():
    """
    Displays repositories and allows deletion of selected ones.
    """
    if request.method == 'GET':
        access_token = get_installation_access_token()
        if not access_token:
            return "Failed to authenticate with GitHub", 500

        repositories = get_github_repositories(access_token)
        if repositories is None:
            return "Failed to fetch repositories", 500
        return render_template('delete_repo.html', repositories=repositories)

    # POST: delete selected repositories
    repos_to_delete = request.form.getlist('repo_to_delete[]')
    if not repos_to_delete:
        return "No repositories selected for deletion", 400

    result_message = delete_repository(repos_to_delete)
    logging.info(result_message)
    flash(result_message)
    return redirect(url_for('main.delete_repositories'))
