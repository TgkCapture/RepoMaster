"""content_routes.py

Browsing repository contents and creating, updating and deleting files.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from app.routes import main_routes
from app.controllers.auth_controller import login_required
from app.controllers.issues_controller import get_github_issues
from app.controllers.repo_controller import get_branches, get_repository_contents, create_file, update_file, delete_file
from app.controllers.pull_requests_controller import get_pull_requests

def _back_to_contents(owner, repo, file_path='', branch=None):
    """Redirect to the directory containing file_path, on the same branch."""
    parent_dir = file_path.strip('/').rpartition('/')[0]
    return redirect(url_for('main.get_contents', owner=owner, repo=repo,
                            path=parent_dir or None, branch=branch or None))

@main_routes.route('/github/repos/<owner>/<repo>/contents', methods=['GET'])
@login_required
def get_contents(owner, repo):
    path = request.args.get('path', '')
    branch = request.args.get('branch')

    contents = get_repository_contents(owner, repo, path, branch)
    if isinstance(contents, dict):
        # A single file was requested; show it as a one-item listing
        contents = [contents]
    branches = get_branches(owner, repo)
    issues = get_github_issues(repo)
    pull_requests = get_pull_requests(owner, repo)

    return render_template(
        'contents.html',
        owner=owner,
        repo=repo,
        contents=contents,
        current_path=path,
        current_branch=branch,
        branches=branches,
        issues=issues,
        pull_requests=pull_requests
    )

@main_routes.route('/github/repos/<owner>/<repo>/contents', methods=['POST'])
@login_required
def create_new_file(owner, repo):
    """
    Create a new file in the repository.
    """
    file_name = (request.form.get('path') or '').strip()
    content = request.form.get('content') or ''
    message = request.form.get('message') or 'Add new file'
    branch = request.form.get('branch')

    if not file_name:
        flash("Failed to create file: file name is required", "danger")
        return _back_to_contents(owner, repo, branch=branch)

    result = create_file(owner, repo, file_name, content, message, branch)
    if result:
        flash(f"File '{file_name}' created successfully", "success")
    else:
        flash("Failed to create file", "danger")
    return _back_to_contents(owner, repo, file_name, branch)

@main_routes.route('/github/repos/<owner>/<repo>/files/update/<path:path>', methods=['POST'])
@login_required
def update_existing_file(owner, repo, path):
    logging.debug(f"Received request to update file: owner={owner}, repo={repo}, path={path}")
    content = request.form.get('content') or ''
    sha = request.form.get('sha')
    message = request.form.get('message') or 'Update file'
    branch = request.form.get('branch')

    if not sha:
        flash("Failed to update file: missing file SHA", "danger")
        return _back_to_contents(owner, repo, path, branch)

    result = update_file(owner, repo, path, content, sha, message, branch)
    if result:
        flash(f"File '{path}' updated successfully", "success")
    else:
        flash("Failed to update file", "danger")
    return _back_to_contents(owner, repo, path, branch)

@main_routes.route('/github/repos/<owner>/<repo>/files/delete/<path:path>', methods=['POST'])
@login_required
def delete_existing_file(owner, repo, path):
    sha = request.form.get('sha')  # delete_file looks the SHA up if it is missing
    message = request.form.get('message') or 'Delete file'
    branch = request.form.get('branch')

    result = delete_file(owner, repo, path, sha, message, branch)
    if result:
        flash(f"File '{path}' deleted successfully", "success")
    else:
        flash("Failed to delete file", "danger")
    return _back_to_contents(owner, repo, path, branch)
