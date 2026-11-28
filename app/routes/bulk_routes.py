"""bulk_routes.py

Bulk repository actions (issue #35): choose repositories and an action, confirm the
exact list of changes, then apply it as a background job and follow its progress and
per-repository report on the job page (issue #54).
"""
import logging
from flask import render_template, request, redirect, url_for, flash, session
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import get_github_repositories
from app.controllers.collaborators_controller import ROLES
from app.controllers.soft_delete_controller import soft_delete_days
from app.controllers.bulk_controller import (
    ACTIONS, DELETE_CONFIRMATION_TEXT, validate_bulk_request, describe_bulk_request,
    is_delete_confirmed, run_bulk_job,
)
from app.controllers.jobs_controller import create_job, start_job

def _render_confirm(bulk_request, error=None, status=200):
    return render_template('bulk_confirm.html', bulk_request=bulk_request,
                           summary=describe_bulk_request(bulk_request), error=error,
                           delete_confirmation_text=DELETE_CONFIRMATION_TEXT, days=soft_delete_days()), status

def _bulk_request_from_form():
    return validate_bulk_request(
        action=request.form.get('action'),
        repo_full_names=request.form.getlist('repos'),
        topics_raw=request.form.get('topics', ''),
        branch=request.form.get('branch', ''),
        login=request.form.get('login', ''),
        role=request.form.get('role', ''),
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

    return render_template('bulk_actions.html', repositories=repositories, actions=ACTIONS, roles=ROLES)

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

    return _render_confirm(bulk_request)

@main_routes.route('/repositories/bulk/apply', methods=['POST'])
@login_required
def bulk_actions_apply():
    """
    Step 3: start the confirmed action as a background job and go to its progress page.
    """
    bulk_request, error = _bulk_request_from_form()
    if error:
        flash(error, "danger")
        return redirect(url_for('main.bulk_actions'))

    if not is_delete_confirmed(bulk_request, request.form.get('confirmation')):
        return _render_confirm(bulk_request, status=400,
                               error=f"Type '{DELETE_CONFIRMATION_TEXT}' to confirm permanent deletion.")

    # Fail fast, while the user is still here, if GitHub won't give us a token
    if not get_installation_access_token():
        flash("Failed to authenticate with GitHub.", "danger")
        return redirect(url_for('main.bulk_actions'))

    installation_id = session['installation_id']
    actor = session.get('github_user_login')
    job_id = create_job(installation_id, actor, 'bulk', describe_bulk_request(bulk_request),
                        len(bulk_request['repos']))
    logging.info(f"Bulk action '{bulk_request['action']}' on {len(bulk_request['repos'])} repositories: job {job_id}.")
    start_job(job_id, run_bulk_job, bulk_request, installation_id, actor)
    return redirect(url_for('main.job_status', job_id=job_id))
