"""collaborator_routes.py

Collaborator and team management for one repository (issue #48).
Bulk add / remove across repositories lives in the bulk actions (bulk_routes.py).
"""
import logging
from flask import flash, redirect, render_template, request, session, url_for
from app.routes import main_routes
from app.controllers.audit_controller import record_audit
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.branch_management_controller import valid_names
from app.controllers.collaborators_controller import (
    ROLES, apply_collaborator_action, list_collaborators, list_invitations, list_organization_teams,
    list_repository_teams, role_label, validate_collaborator_action,
)


def _is_organization():
    return session.get('github_account_type') == 'Organization'


@main_routes.route('/repos/<owner>/<repo>/collaborators', methods=['GET'])
@login_required
def collaborators(owner, repo):
    """Collaborators, pending invitations and (for organizations) teams."""
    if not valid_names(owner, repo):
        return "Invalid repository name", 400
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    people, people_error = list_collaborators(owner, repo, access_token)
    invitations, invitations_error = list_invitations(owner, repo, access_token)

    teams = available_teams = teams_error = None
    if _is_organization():
        teams, teams_error = list_repository_teams(owner, repo, access_token)
        org_teams, _ = list_organization_teams(owner, access_token)
        if teams is not None and org_teams is not None:
            granted = {team['slug'] for team in teams}
            available_teams = [team for team in org_teams if team['slug'] not in granted]

    return render_template(
        'collaborators.html', owner=owner, repo=repo, roles=ROLES, role_label=role_label,
        people=people, people_error=people_error,
        invitations=invitations, invitations_error=invitations_error,
        is_organization=_is_organization(), teams=teams, teams_error=teams_error, available_teams=available_teams,
    )


@main_routes.route('/repos/<owner>/<repo>/collaborators', methods=['POST'])
@login_required
def collaborators_action(owner, repo):
    """Invite, change or remove a collaborator, invitation or team."""
    if not valid_names(owner, repo):
        return "Invalid repository name", 400
    back = redirect(url_for('main.collaborators', owner=owner, repo=repo))

    params, error = validate_collaborator_action(request.form.get('action'), request.form, owner, _is_organization())
    if error:
        flash(error, 'danger')
        return back

    access_token = get_installation_access_token()
    if not access_token:
        flash("Failed to authenticate with GitHub.", 'danger')
        return back

    message, error = apply_collaborator_action(owner, repo, params, access_token)
    target = params.get('login') or params.get('team') or (f"invitation {params['invitation_id']}"
                                                           if 'invitation_id' in params else None)
    record_audit(f"collaborator.{params['action']}", f'{owner}/{repo}', error is None, error or message, target=target)
    if error:
        flash(f"GitHub refused the change: {error}", 'danger')
    else:
        logging.info(f"Collaborator action {params['action']} on {owner}/{repo}")
        flash(message, 'success')
    return back
