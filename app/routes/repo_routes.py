"""repo_routes.py

Repository listing, repository details and deletion (archived first, deleted after a
grace period; see soft_delete_controller).
"""
import logging
from flask import render_template, request, redirect, url_for, flash, session
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.branch_management_controller import valid_names
from app.controllers.repo_controller import get_github_repositories, get_branches
from app.controllers.soft_delete_controller import schedule_deletion, soft_delete_days
from app.controllers.repo_list_controller import (
    SORTS, VISIBILITIES, active_filters, filter_and_sort, language_options, paginate, parse_repo_filters,
)

@main_routes.route('/github/repositories')
@login_required
def show_github_repositories():
    """
    Display the repositories the GitHub App installation can access, with search,
    filters, sorting and pagination (all in the query string, so links can be shared).
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
    languages = language_options(repositories)
    filters = parse_repo_filters(request.args, languages)
    matching = filter_and_sort(repositories, filters)
    page_items, page, pages = paginate(matching, request.args.get('page'))
    return render_template('repositories.html', repositories=page_items, total=len(repositories),
                           matching=len(matching), page=page, pages=pages, filters=filters,
                           link_filters=active_filters(filters), languages=languages,
                           sorts=SORTS, visibilities=VISIBILITIES)

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
        return render_template('delete_repo.html', repositories=repositories, days=soft_delete_days())

    # POST: archive the selected repositories and schedule their deletion
    repos_to_delete = list(dict.fromkeys(request.form.getlist('repo_to_delete[]')))
    if not repos_to_delete:
        return "No repositories selected for deletion", 400

    owner = session.get('github_username')
    if not owner:
        flash("Could not determine the repository owner. Please log in again.", 'danger')
        return redirect(url_for('main.delete_repositories'))

    access_token = get_installation_access_token()
    if not access_token:
        flash("Access token missing. Cannot delete repositories.", 'danger')
        return redirect(url_for('main.delete_repositories'))

    for repo_name in repos_to_delete:
        if not valid_names(owner, repo_name):
            flash(f"Invalid repository name: {repo_name}", 'danger')
            continue
        ok, message = schedule_deletion(owner, repo_name, access_token)
        logging.info(f"Delete {owner}/{repo_name}: {message}")
        flash(message if ok else f"Couldn't delete {owner}/{repo_name}: {message}", 'success' if ok else 'danger')
    return redirect(url_for('main.delete_repositories'))
