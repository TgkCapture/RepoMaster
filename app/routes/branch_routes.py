"""branch_routes.py

Creating, viewing, renaming and deleting branches.
"""
import logging
import requests
from flask import render_template, request, redirect, url_for, session, flash
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, is_user_logged_in
from app.controllers.repo_controller import get_branch_details, create_branch, get_default_branch_sha

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
