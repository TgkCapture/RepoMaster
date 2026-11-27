"""collaborators_controller.py

Collaborator and team management (issue #48): who has access to a repository, pending
invitations, and team access on organization repositories. Calls go through
repo_controller.github_api; owner / repo names are checked by the routes.

GitHub names the same permission levels differently per endpoint: collaborator and team
PUTs take pull / push, while roles and invitations use read / write. RepoMaster uses the
role names everywhere and converts at the edges.
"""
import re
from urllib.parse import quote
from app.controllers.repo_controller import github_api
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago

# role -> (label, what it allows), least to most access
ROLES = {
    'read': ('Read', 'View and clone, open issues'),
    'triage': ('Triage', 'Read, plus manage issues and pull requests'),
    'write': ('Write', 'Triage, plus push to the repository'),
    'maintain': ('Maintain', 'Write, plus manage some settings'),
    'admin': ('Admin', 'Full access, including deleting the repository'),
}
ROLE_TO_API = {'read': 'pull', 'write': 'push'}
API_TO_ROLE = {api: role for role, api in ROLE_TO_API.items()}

LOGIN_PATTERN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$')
TEAM_SLUG_PATTERN = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$')

# action -> fields it needs from the form
ACTIONS = {
    'invite': ('login', 'role'),
    'set_role': ('login', 'role'),
    'remove': ('login',),
    'invitation_role': ('invitation_id', 'role'),
    'cancel_invitation': ('invitation_id',),
    'team_add': ('team', 'role'),
    'team_role': ('team', 'role'),
    'team_remove': ('team',),
}
TEAM_ACTIONS = {'team_add', 'team_role', 'team_remove'}


def to_role(permission):
    """Any GitHub permission name -> role name (custom roles pass through unchanged)."""
    return API_TO_ROLE.get(permission, permission)


def role_label(role):
    return ROLES[role][0] if role in ROLES else (role or 'unknown').replace('_', ' ').capitalize()


def _repo_path(owner, repo):
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


def _user(data):
    data = data or {}
    return {'login': data.get('login') or 'unknown', 'avatar_url': data.get('avatar_url'), 'html_url': data.get('html_url')}


def list_collaborators(owner, repo, access_token):
    """Returns (rows, None) or (None, error). Each row: login, avatar_url, html_url, role, is_owner."""
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/collaborators', access_token,
                             params={'affiliation': 'all', 'per_page': 100})
    if error:
        return None, error
    rows = []
    for entry in data or []:
        role = entry.get('role_name') or _highest_permission(entry.get('permissions'))
        rows.append({**_user(entry), 'role': to_role(role), 'is_owner': (entry.get('login') or '').lower() == owner.lower()})
    rows.sort(key=lambda row: (not row['is_owner'], row['login'].lower()))
    return rows, None


def _highest_permission(permissions):
    for role in ('admin', 'maintain', 'push', 'triage', 'pull'):
        if (permissions or {}).get(role):
            return role
    return None


def list_invitations(owner, repo, access_token):
    """Pending invitations. Returns (rows, None) or (None, error)."""
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/invitations', access_token, params={'per_page': 100})
    if error:
        return None, error
    rows = []
    for invitation in data or []:
        created = parse_github_date(invitation.get('created_at'))
        rows.append({
            'id': invitation.get('id'),
            'invitee': _user(invitation.get('invitee')),
            'inviter': _user(invitation.get('inviter'))['login'],
            'role': to_role(invitation.get('permissions')),
            'expired': bool(invitation.get('expired')),
            'created_ago': time_ago(created),
        })
    return rows, None


def list_repository_teams(owner, repo, access_token):
    """Teams with access to the repository. Returns (rows, None) or (None, error)."""
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/teams', access_token, params={'per_page': 100})
    if error:
        return None, error
    rows = [{'slug': t.get('slug'), 'name': t.get('name') or t.get('slug'), 'html_url': t.get('html_url'),
             'role': to_role(t.get('permission'))} for t in data or []]
    rows.sort(key=lambda row: row['name'].lower())
    return rows, None


def list_organization_teams(org, access_token):
    """All teams in the organization, for the 'add team' picker. Returns (rows, None) or (None, error)."""
    data, error = github_api('GET', f'/orgs/{quote(org, safe="")}/teams', access_token, params={'per_page': 100})
    if error:
        return None, error
    rows = [{'slug': t.get('slug'), 'name': t.get('name') or t.get('slug')} for t in data or []]
    rows.sort(key=lambda row: row['name'].lower())
    return rows, None


def validate_collaborator_action(action, form, owner, is_organization):
    """
    Check a form submission. Returns (params, None) or (None, error_message);
    params holds the cleaned fields the action needs.
    """
    if action not in ACTIONS:
        return None, "Unknown action."
    if action in TEAM_ACTIONS and not is_organization:
        return None, "Teams only exist on organization repositories."

    params = {'action': action}
    for field in ACTIONS[action]:
        value = (form.get(field) or '').strip()
        if field == 'login':
            value = value.lstrip('@')
            if not LOGIN_PATTERN.match(value):
                return None, "Enter a valid GitHub username."
            if value.lower() == owner.lower():
                return None, ("The repository owner already has full access." if action == 'invite'
                              else "The repository owner's access can't be changed.")
        elif field == 'role':
            if value not in ROLES:
                return None, "Choose a permission level."
        elif field == 'invitation_id':
            if not value.isdigit():
                return None, "Invalid invitation."
            value = int(value)
        elif field == 'team':
            if not TEAM_SLUG_PATTERN.match(value):
                return None, "Choose a team."
        params[field] = value
    return params, None


def add_collaborator(owner, repo, login, role, access_token):
    """
    Invite a user, or change an existing collaborator's permission (same request).
    Returns (message, None) or (None, error).
    """
    data, error = github_api('PUT', f'{_repo_path(owner, repo)}/collaborators/{quote(login, safe="")}', access_token,
                             json={'permission': ROLE_TO_API.get(role, role)})
    if error:
        return None, error
    # 201 with an invitation for a new collaborator, 204 (no body) when access was updated directly
    if data:
        return f"Invited {login} with {role_label(role)} access. They need to accept the invitation.", None
    return f"{login} now has {role_label(role)} access.", None


def is_collaborator(owner, repo, login, access_token):
    """True / False, or None if GitHub couldn't be asked."""
    _, error = github_api('GET', f'{_repo_path(owner, repo)}/collaborators/{quote(login, safe="")}', access_token)
    if error is None:
        return True
    return False if error in ('Not Found', 'GitHub returned status 404') else None


def remove_collaborator(owner, repo, login, access_token):
    """Returns (message, None) or (None, error)."""
    _, error = github_api('DELETE', f'{_repo_path(owner, repo)}/collaborators/{quote(login, safe="")}', access_token)
    return (None, error) if error else (f"Removed {login}'s access.", None)


def update_invitation(owner, repo, invitation_id, role, access_token):
    _, error = github_api('PATCH', f'{_repo_path(owner, repo)}/invitations/{invitation_id}', access_token,
                          json={'permissions': role})
    return (None, error) if error else (f"Invitation changed to {role_label(role)} access.", None)


def cancel_invitation(owner, repo, invitation_id, access_token):
    _, error = github_api('DELETE', f'{_repo_path(owner, repo)}/invitations/{invitation_id}', access_token)
    return (None, error) if error else ("Invitation cancelled.", None)


def _team_path(org, slug, owner, repo):
    return f'/orgs/{quote(org, safe="")}/teams/{quote(slug, safe="")}/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


def set_team_access(org, slug, owner, repo, role, access_token):
    _, error = github_api('PUT', _team_path(org, slug, owner, repo), access_token,
                          json={'permission': ROLE_TO_API.get(role, role)})
    return (None, error) if error else (f"Team {slug} now has {role_label(role)} access.", None)


def remove_team_access(org, slug, owner, repo, access_token):
    _, error = github_api('DELETE', _team_path(org, slug, owner, repo), access_token)
    return (None, error) if error else (f"Removed team {slug}'s access.", None)


def apply_collaborator_action(owner, repo, params, access_token):
    """Run a validated action. Returns (message, None) or (None, error)."""
    action = params['action']
    if action in ('invite', 'set_role'):
        return add_collaborator(owner, repo, params['login'], params['role'], access_token)
    if action == 'remove':
        return remove_collaborator(owner, repo, params['login'], access_token)
    if action == 'invitation_role':
        return update_invitation(owner, repo, params['invitation_id'], params['role'], access_token)
    if action == 'cancel_invitation':
        return cancel_invitation(owner, repo, params['invitation_id'], access_token)
    if action in ('team_add', 'team_role'):
        return set_team_access(owner, params['team'], owner, repo, params['role'], access_token)
    return remove_team_access(owner, params['team'], owner, repo, access_token)


def remove_access(owner, repo, login, access_token):
    """
    Remove a user's access for the bulk action: drop them as a collaborator and cancel any
    pending invitation. Returns (ok, message), saying 'no change' when they had neither.
    """
    invitations, error = list_invitations(owner, repo, access_token)
    if error:
        return False, error
    pending = [i for i in invitations if i['invitee']['login'].lower() == login.lower()]
    for invitation in pending:
        _, error = cancel_invitation(owner, repo, invitation['id'], access_token)
        if error:
            return False, error

    member = is_collaborator(owner, repo, login, access_token)
    if member is None:
        return False, "Couldn't check whether they are a collaborator"
    if member:
        _, error = remove_collaborator(owner, repo, login, access_token)
        if error:
            return False, error
        return True, "Removed" + (" and cancelled the invitation" if pending else "")
    return True, "Invitation cancelled" if pending else "Not a collaborator, no change"
