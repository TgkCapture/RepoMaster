"""branch_routes.py

Creating, viewing, renaming and deleting branches.
"""
import logging
import requests
from app import github_http
from flask import render_template, request, redirect, url_for, session, flash
from app.routes import main_routes
from app.controllers.audit_controller import record_audit
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import (
    get_branch_details, create_branch, get_default_branch_sha, get_repository, list_branches,
)
from app.controllers.branch_management_controller import (
    MAX_APPROVALS, build_protection_payload, commit_rows, compare_branches, describe_comparison,
    find_open_pull_request, get_protection, protection_to_form, remove_protection, save_protection,
    valid_branch, valid_names,
)
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago

REQUEST_TIMEOUT = 60  # seconds

def _branch_details_url(owner, repo_name, branch_name):
    return url_for('main.show_branch_details', owner=owner, repo_name=repo_name, branch_name=branch_name)

@main_routes.route('/repos/<owner>/<repo_name>/git/refs', methods=['GET', 'POST'])
@login_required
def main_create_branch(owner, repo_name):
    """
    Render the branch creation form and handle branch creation in the repository.
    """
    if request.method == 'GET':
        return render_template('create_branch.html', owner=owner, repo_name=repo_name)

    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to get access token for creating a branch.")
        flash("Failed to authenticate with GitHub.", "error")
        return redirect(request.url)

    ref_name = request.form.get("ref")
    sha = request.form.get("sha")

    if not ref_name:
        flash("Branch name is required.", "error")
        return redirect(request.url)

    if not sha:
        sha = get_default_branch_sha(owner, repo_name, access_token)
        if not sha:
            flash("Failed to retrieve default branch information.", "error")
            return redirect(request.url)

    branch = create_branch(owner, repo_name, access_token, ref_name, sha)
    if branch:
        logging.info(f"Successfully created branch '{ref_name}' in repository '{owner}/{repo_name}'.")
        flash(f"Branch '{ref_name}' successfully created.", "success")
        return redirect(_branch_details_url(owner, repo_name, ref_name))

    logging.error(f"Failed to create branch '{ref_name}' in repository '{owner}/{repo_name}'.")
    flash("Failed to create branch in the repository.", "error")
    return redirect(request.url)

@main_routes.route('/github/repository/branch-details')
@login_required
def show_branch_details():
    """
    Display details of a specific branch.
    Query params: repo_name, branch_name, and optionally owner (defaults to the logged-in account).
    """
    owner = request.args.get('owner') or session.get('github_username')
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
@login_required
def delete_branch(owner, repo_name, branch_name):
    access_token = get_installation_access_token()
    if not access_token:
        flash("Authentication failed.", "error")
        return redirect(_branch_details_url(owner, repo_name, branch_name))

    url = f'https://api.github.com/repos/{owner}/{repo_name}/git/refs/heads/{branch_name}'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = github_http.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logging.error(f"Failed to delete branch '{branch_name}' in '{owner}/{repo_name}': {e}")
        response = None

    deleted = response is not None and response.status_code == 204
    record_audit('branch.delete', f'{owner}/{repo_name}', deleted, 'Deleted' if deleted else 'GitHub refused', target=branch_name)
    if deleted:
        flash(f"Branch '{branch_name}' successfully deleted.", "success")
    else:
        flash(f"Failed to delete branch '{branch_name}'.", "error")
    return redirect(url_for('main.show_repo_details', owner=owner, repo_name=repo_name))

@main_routes.route('/repos/<owner>/<repo_name>/branches/<branch_name>/rename', methods=['POST'])
@login_required
def rename_branch(owner, repo_name, branch_name):
    access_token = get_installation_access_token()
    if not access_token:
        flash("Authentication failed.", "error")
        return redirect(_branch_details_url(owner, repo_name, branch_name))

    new_name = request.form.get('new_name')
    if not new_name:
        flash("New branch name is required.", "error")
        return redirect(_branch_details_url(owner, repo_name, branch_name))

    url = f'https://api.github.com/repos/{owner}/{repo_name}/branches/{branch_name}/rename'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    payload = {'new_name': new_name}

    try:
        response = github_http.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        logging.error(f"Failed to rename branch '{branch_name}' in '{owner}/{repo_name}': {e}")
        record_audit('branch.rename', f'{owner}/{repo_name}', False, 'Could not reach GitHub', target=branch_name)
        flash(f"Failed to rename branch '{branch_name}'.", "error")
        return redirect(_branch_details_url(owner, repo_name, branch_name))

    if response.status_code == 201:
        record_audit('branch.rename', f'{owner}/{repo_name}', True, f"Renamed to {new_name}", target=branch_name)
        flash(f"Branch '{branch_name}' renamed to '{new_name}'.", "success")
        return redirect(url_for('main.show_repo_details', owner=owner, repo_name=repo_name))

    try:
        error_message = response.json().get('message', 'An error occurred.')
    except ValueError:
        error_message = 'An error occurred.'
    record_audit('branch.rename', f'{owner}/{repo_name}', False, error_message, target=branch_name)
    flash(f"Failed to rename branch '{branch_name}': {error_message}", "error")
    return redirect(_branch_details_url(owner, repo_name, branch_name))


# --- Branch protection and comparison (issue #41) ----------------------------

def _protection_url(owner, repo_name, branch):
    return url_for('main.branch_protection', owner=owner, repo_name=repo_name, branch=branch)


@main_routes.route('/repos/<owner>/<repo_name>/branch-protection', methods=['GET', 'POST'])
@login_required
def branch_protection(owner, repo_name):
    """View and edit a branch's protection rules. The branch is given as ?branch=name."""
    branch = request.values.get('branch', '')
    if not valid_names(owner, repo_name) or not valid_branch(branch):
        return "Invalid repository or branch name", 400

    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    protection, error = get_protection(owner, repo_name, branch, access_token)
    if error:
        logging.error(f"Failed to fetch protection for {owner}/{repo_name}:{branch}: {error}")
        if request.method == 'POST':
            flash(f"Couldn't load the current protection rules: {error}", 'error')
            return redirect(_protection_url(owner, repo_name, branch))
        return render_template('branch_protection.html', owner=owner, repo=repo_name, branch=branch,
                               settings=protection_to_form(None), load_error=error,
                               max_approvals=MAX_APPROVALS), 502

    if request.method == 'GET':
        return render_template('branch_protection.html', owner=owner, repo=repo_name, branch=branch,
                               settings=protection_to_form(protection), load_error=None,
                               max_approvals=MAX_APPROVALS)

    if request.form.get('action') == 'remove':
        if protection is None:
            flash(f"{branch} isn't protected.", 'info')
            return redirect(_protection_url(owner, repo_name, branch))
        removed, error = remove_protection(owner, repo_name, branch, access_token)
        record_audit('branch.protection_remove', f'{owner}/{repo_name}', removed, error or 'Removed', target=branch)
        flash(f"Protection removed from {branch}." if removed else f"Couldn't remove protection: {error}",
              'success' if removed else 'error')
        return redirect(_protection_url(owner, repo_name, branch))

    payload, error = build_protection_payload(request.form, protection)
    if not error:
        _, error = save_protection(owner, repo_name, branch, access_token, payload)
        record_audit('branch.protection_update', f'{owner}/{repo_name}', error is None, error or 'Saved', target=branch)
    if error:
        logging.warning(f"Saving protection for {owner}/{repo_name}:{branch} failed: {error}")
        flash(f"Couldn't save protection rules: {error}", 'error')
    else:
        flash(f"Protection rules for {branch} saved.", 'success')
    return redirect(_protection_url(owner, repo_name, branch))


@main_routes.route('/repos/<owner>/<repo_name>/compare', methods=['GET'])
@login_required
def compare_branches_page(owner, repo_name):
    """Compare two branches (?base=...&head=...): ahead/behind counts and the commit list."""
    if not valid_names(owner, repo_name):
        return "Invalid repository name", 400
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    branches, error = list_branches(owner, repo_name, access_token)
    if error:
        return f"Failed to fetch branches: {error}", 500
    branch_names = [b['name'] for b in branches]
    repository, _ = get_repository(owner, repo_name, access_token)
    default_branch = (repository or {}).get('default_branch')

    base = request.args.get('base') or default_branch or ''
    head = request.args.get('head', '')
    context = {'owner': owner, 'repo': repo_name, 'branches': branch_names, 'base': base, 'head': head,
               'comparison': None, 'error': None, 'commits': [], 'summary': None, 'open_pull': None,
               'session_owner': session.get('github_username')}

    if base and head:
        if not valid_branch(base) or not valid_branch(head):
            context['error'] = "Choose two valid branch names."
        elif base == head:
            context['error'] = "Choose two different branches."
        else:
            comparison, error = compare_branches(owner, repo_name, base, head, access_token)
            if error:
                context['error'] = f"Couldn't compare {base} and {head}: {error}"
            else:
                context.update(comparison=comparison, summary=describe_comparison(comparison, base, head),
                               commits=commit_rows(comparison.get('commits')))
                for commit in context['commits']:
                    commit['ago'] = time_ago(parse_github_date(commit['date']))
                if comparison.get('ahead_by'):
                    context['open_pull'] = find_open_pull_request(owner, repo_name, base, head, access_token)

    return render_template('compare_branches.html', **context)
