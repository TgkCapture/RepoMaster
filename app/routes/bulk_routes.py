"""bulk_routes.py

Bulk repository actions (issue #35): choose repositories and an action, confirm the
exact list of changes, then apply it and see a per-repository report.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import get_github_repositories
from app.controllers.bulk_controller import (
    ACTIONS, validate_bulk_request, describe_bulk_request, apply_bulk_action,
)

def _bulk_request_from_form():
    return validate_bulk_request(
        action=request.form.get('action'),
        repo_full_names=request.form.getlist('repos'),
        topics_raw=request.form.get('topics', ''),
        branch=request.form.get('branch', ''),
    )

@main_routes.route('/repositories/bulk', methods=['GET'])
@login_required
def bulk_actions():
    """
    Step 1: pick repositories and an action.
    """
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    repositories = get_github_repositories(access_token)
    if repositories is None:
        return "Failed to fetch repositories from GitHub", 500

    return render_template('bulk_actions.html', repositories=repositories, actions=ACTIONS)

@main_routes.route('/repositories/bulk/confirm', methods=['POST'])
@login_required
def bulk_actions_confirm():
    """
    Step 2: show exactly which repositories will change, and how.
    """
    bulk_request, error = _bulk_request_from_form()
    if error:
        flash(error, "danger")
        return redirect(url_for('main.bulk_actions'))

    return render_template('bulk_confirm.html', bulk_request=bulk_request,
                           summary=describe_bulk_request(bulk_request))

@main_routes.route('/repositories/bulk/apply', methods=['POST'])
@login_required
def bulk_actions_apply():
    """
    Step 3: apply the confirmed action and report the result for each repository.
    """
    bulk_request, error = _bulk_request_from_form()
    if error:
        flash(error, "danger")
        return redirect(url_for('main.bulk_actions'))

    access_token = get_installation_access_token()
    if not access_token:
        flash("Failed to authenticate with GitHub.", "danger")
        return redirect(url_for('main.bulk_actions'))

    results = apply_bulk_action(access_token, bulk_request)
    logging.info(f"Bulk action '{bulk_request['action']}' applied to {len(results)} repositories.")
    return render_template('bulk_results.html', results=results,
                           summary=describe_bulk_request(bulk_request),
                           succeeded=sum(1 for r in results if r['ok']))
