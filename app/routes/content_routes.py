"""content_routes.py

Browsing repository contents and creating, updating and deleting files.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token
from app.controllers.issues_controller import get_github_issues
from app.controllers.repo_controller import get_branches, get_repository_contents, create_file, update_file, delete_file
from app.controllers.pull_requests_controller import get_pull_requests

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
