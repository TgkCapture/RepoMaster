"""Tests for collaborator and team management (issue #48). GitHub is never contacted."""
import pytest

from app.controllers import collaborators_controller
from app.controllers.bulk_controller import apply_bulk_action, describe_bulk_request, validate_bulk_request
from app.controllers.collaborators_controller import (
    add_collaborator, list_collaborators, list_invitations, list_repository_teams, remove_access, role_label,
    to_role, validate_collaborator_action,
)
from app.routes import collaborator_routes

BASE = '/repos/alice/app'
COLLABORATORS = [
    {'login': 'bob', 'avatar_url': 'https://avatars/bob', 'html_url': 'https://github.com/bob', 'role_name': 'write'},
    {'login': 'alice', 'html_url': 'https://github.com/alice', 'role_name': 'admin'},
    {'login': 'carol', 'html_url': 'https://github.com/carol', 'permissions': {'pull': True, 'triage': True}},
    {'login': 'dave', 'html_url': 'https://github.com/dave', 'role_name': 'security_manager'},
]
INVITATIONS = [{'id': 77, 'invitee': {'login': 'erin'}, 'inviter': {'login': 'alice'}, 'permissions': 'read',
                'created_at': '2026-11-20T10:00:00Z', 'expired': False}]
TEAMS = [{'slug': 'core', 'name': 'Core', 'html_url': 'https://github.com/orgs/acme/teams/core', 'permission': 'push'}]


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: (method, path) -> (data, error). Unknown requests answer 404."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(collaborators_controller, 'github_api', fake_api)
    monkeypatch.setattr(collaborator_routes, 'get_installation_access_token', lambda: 'tok')
    return state


def writes(github):
    return [call for call in github['calls'] if call[0] != 'GET']


# --- Listing -----------------------------------------------------------------

def test_roles_are_normalized():
    assert to_role('pull') == 'read' and to_role('push') == 'write' and to_role('maintain') == 'maintain'
    assert role_label('write') == 'Write' and role_label('security_manager') == 'Security manager'


def test_list_collaborators(github):
    github['responses'][('GET', f'{BASE}/collaborators')] = (COLLABORATORS, None)
    rows, error = list_collaborators('alice', 'app', 'tok')
    assert error is None
    assert [(r['login'], r['role'], r['is_owner']) for r in rows] == [
        ('alice', 'admin', True), ('bob', 'write', False), ('carol', 'triage', False), ('dave', 'security_manager', False)]


def test_list_invitations_and_teams(github):
    github['responses'][('GET', f'{BASE}/invitations')] = (INVITATIONS, None)
    github['responses'][('GET', f'{BASE}/teams')] = (TEAMS, None)
    invitation = list_invitations('alice', 'app', 'tok')[0][0]
    assert invitation['id'] == 77 and invitation['invitee']['login'] == 'erin' and invitation['role'] == 'read'
    assert list_repository_teams('alice', 'app', 'tok')[0] == [
        {'slug': 'core', 'name': 'Core', 'html_url': 'https://github.com/orgs/acme/teams/core', 'role': 'write'}]


# --- Validation --------------------------------------------------------------

@pytest.mark.parametrize('action, form, is_org, error', [
    ('nope', {}, False, 'Unknown action.'),
    ('invite', {'login': 'bad name', 'role': 'write'}, False, 'Enter a valid GitHub username.'),
    ('invite', {'login': 'bob', 'role': 'owner'}, False, 'Choose a permission level.'),
    ('invite', {'login': 'Alice', 'role': 'write'}, False, 'The repository owner already has full access.'),
    ('remove', {'login': 'alice'}, False, "The repository owner's access can't be changed."),
    ('cancel_invitation', {'invitation_id': '7; DROP'}, False, 'Invalid invitation.'),
    ('team_add', {'team': 'core', 'role': 'read'}, False, 'Teams only exist on organization repositories.'),
    ('team_add', {'team': '../x', 'role': 'read'}, True, 'Choose a team.'),
])
def test_validation_errors(action, form, is_org, error):
    assert validate_collaborator_action(action, form, 'alice', is_org) == (None, error)


def test_validation_cleans_values():
    params, _ = validate_collaborator_action('invite', {'login': ' @bob ', 'role': 'maintain'}, 'alice', False)
    assert params == {'action': 'invite', 'login': 'bob', 'role': 'maintain'}
    params, _ = validate_collaborator_action('invitation_role', {'invitation_id': '77', 'role': 'read'}, 'alice', False)
    assert params['invitation_id'] == 77


# --- Changes -----------------------------------------------------------------

def test_add_collaborator_invites_or_updates(github):
    github['responses'][('PUT', f'{BASE}/collaborators/bob')] = ({'id': 5, 'invitee': {'login': 'bob'}}, None)
    message, _ = add_collaborator('alice', 'app', 'bob', 'read', 'tok')
    assert message.startswith('Invited bob with Read access')
    assert github['calls'][-1] == ('PUT', f'{BASE}/collaborators/bob', {'permission': 'pull'})

    github['responses'][('PUT', f'{BASE}/collaborators/bob')] = (None, None)  # 204: already a collaborator
    assert add_collaborator('alice', 'app', 'bob', 'write', 'tok')[0] == 'bob now has Write access.'
    assert github['calls'][-1][2] == {'permission': 'push'}


@pytest.mark.parametrize('form, call', [
    ({'action': 'set_role', 'login': 'bob', 'role': 'triage'}, ('PUT', f'{BASE}/collaborators/bob', {'permission': 'triage'})),
    ({'action': 'remove', 'login': 'bob'}, ('DELETE', f'{BASE}/collaborators/bob', None)),
    ({'action': 'invitation_role', 'invitation_id': '77', 'role': 'write'},
     ('PATCH', f'{BASE}/invitations/77', {'permissions': 'write'})),
    ({'action': 'cancel_invitation', 'invitation_id': '77'}, ('DELETE', f'{BASE}/invitations/77', None)),
])
def test_page_actions_call_github(logged_in_client, github, form, call):
    github['responses'][call[:2]] = (None, None)
    response = logged_in_client.post('/repos/alice/app/collaborators', data=form)
    assert response.status_code == 302 and response.headers['Location'] == '/repos/alice/app/collaborators'
    assert writes(github) == [call]


@pytest.mark.parametrize('form, call', [
    ({'action': 'team_add', 'team': 'core', 'role': 'maintain'},
     ('PUT', '/orgs/acme/teams/core/repos/acme/app', {'permission': 'maintain'})),
    ({'action': 'team_role', 'team': 'core', 'role': 'read'},
     ('PUT', '/orgs/acme/teams/core/repos/acme/app', {'permission': 'pull'})),
    ({'action': 'team_remove', 'team': 'core'}, ('DELETE', '/orgs/acme/teams/core/repos/acme/app', None)),
])
def test_team_actions_on_organization(logged_in_client, github, form, call):
    with logged_in_client.session_transaction() as sess:
        sess['github_account_type'] = 'Organization'
    github['responses'][call[:2]] = (None, None)
    logged_in_client.post('/repos/acme/app/collaborators', data=form)
    assert writes(github) == [call]


def test_github_error_is_flashed(logged_in_client, github):
    response = logged_in_client.post('/repos/alice/app/collaborators',
                                     data={'action': 'remove', 'login': 'bob'}, follow_redirects=True)
    assert 'GitHub refused the change: Not Found' in response.data.decode()


def test_invalid_input_never_reaches_github(logged_in_client, github):
    response = logged_in_client.post('/repos/alice/app/collaborators',
                                     data={'action': 'invite', 'login': 'x y', 'role': 'write'}, follow_redirects=True)
    assert 'Enter a valid GitHub username.' in response.data.decode() and writes(github) == []


# --- Page --------------------------------------------------------------------

def test_page_lists_people_and_invitations(logged_in_client, github):
    github['responses'][('GET', f'{BASE}/collaborators')] = (COLLABORATORS, None)
    github['responses'][('GET', f'{BASE}/invitations')] = (INVITATIONS, None)
    html = logged_in_client.get('/repos/alice/app/collaborators').data.decode()
    assert 'bob' in html and 'erin' in html and 'invited by alice' in html
    assert 'Security manager (custom)' in html
    # The owner has no remove form
    assert 'name="login" value="alice"' not in html and 'name="login" value="bob"' in html
    assert 'Teams' not in html  # personal account


def test_page_shows_section_errors(logged_in_client, github):
    html = logged_in_client.get('/repos/alice/app/collaborators').data.decode()
    assert 'Could not load collaborators: Not Found' in html and 'Could not load invitations: Not Found' in html


def test_organization_page_offers_teams_without_access(logged_in_client, github):
    with logged_in_client.session_transaction() as sess:
        sess['github_account_type'] = 'Organization'
    github['responses'].update({
        ('GET', '/repos/acme/app/collaborators'): ([], None),
        ('GET', '/repos/acme/app/invitations'): ([], None),
        ('GET', '/repos/acme/app/teams'): (TEAMS, None),
        ('GET', '/orgs/acme/teams'): ([{'slug': 'core', 'name': 'Core'}, {'slug': 'docs', 'name': 'Docs'}], None),
    })
    html = logged_in_client.get('/repos/acme/app/collaborators').data.decode()
    assert 'Core' in html and '<option value="docs">Docs</option>' in html
    assert '<option value="core">' not in html


def test_invalid_repository_name(logged_in_client, github):
    assert logged_in_client.get('/repos/alice/bad%20name/collaborators').status_code == 400
    assert logged_in_client.post('/repos/alice/bad%20name/collaborators').status_code == 400


@pytest.mark.parametrize('method', ['get', 'post'])
def test_requires_login(client, method):
    assert getattr(client, method)('/repos/alice/app/collaborators').status_code == 403


# --- Bulk --------------------------------------------------------------------

def test_bulk_validation():
    request, error = validate_bulk_request('add_collaborator', ['alice/app', 'alice/site'], login='@bob', role='write')
    assert error is None and request['login'] == 'bob' and request['role'] == 'write'
    assert describe_bulk_request(request).startswith('Give bob Write access')
    assert validate_bulk_request('add_collaborator', ['alice/app'], login='bob', role='god')[1] == 'Choose a permission level.'
    assert validate_bulk_request('remove_collaborator', ['alice/app'], login='')[1] == 'Enter a valid GitHub username.'
    assert validate_bulk_request('remove_collaborator', ['alice/app'], login='ALICE')[1] == \
        "The repository owner's access can't be changed."


def test_bulk_add_reports_each_repository(github):
    github['responses'][('PUT', f'{BASE}/collaborators/bob')] = ({'id': 1}, None)
    github['responses'][('PUT', '/repos/alice/site/collaborators/bob')] = (None, None)
    request, _ = validate_bulk_request('add_collaborator', ['alice/app', 'alice/site', 'alice/gone'], login='bob', role='read')
    results = apply_bulk_action('tok', request)
    assert [r['ok'] for r in results] == [True, True, False]
    assert results[0]['message'].startswith('Invited bob') and results[1]['message'] == 'bob now has Read access.'
    assert results[2]['message'] == 'Not Found'


def test_bulk_remove_cancels_invitations_and_reports_no_change(github):
    github['responses'].update({
        ('GET', f'{BASE}/invitations'): ([{**INVITATIONS[0], 'invitee': {'login': 'Bob'}}], None),
        ('DELETE', f'{BASE}/invitations/77'): (None, None),
        ('GET', f'{BASE}/collaborators/bob'): (None, None),
        ('DELETE', f'{BASE}/collaborators/bob'): (None, None),
        ('GET', '/repos/alice/site/invitations'): ([], None),
    })
    request, _ = validate_bulk_request('remove_collaborator', ['alice/app', 'alice/site'], login='bob')
    results = apply_bulk_action('tok', request)
    assert results[0] == {'repo': 'alice/app', 'ok': True, 'message': 'Removed and cancelled the invitation'}
    assert results[1] == {'repo': 'alice/site', 'ok': True, 'message': 'Not a collaborator, no change'}
    assert ('DELETE', '/repos/alice/site/collaborators/bob', None) not in github['calls']


def test_remove_access_when_github_cant_be_asked(github):
    github['responses'][('GET', f'{BASE}/invitations')] = ([], None)
    github['responses'][('GET', f'{BASE}/collaborators/bob')] = (None, 'Could not reach GitHub')
    assert remove_access('alice', 'app', 'bob', 'tok') == (False, "Couldn't check whether they are a collaborator")


def test_bulk_page_and_confirm_carry_collaborator_fields(logged_in_client, monkeypatch):
    from app.routes import bulk_routes
    monkeypatch.setattr(bulk_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(bulk_routes, 'get_github_repositories', lambda token: [{'full_name': 'alice/app'}])
    html = logged_in_client.get('/repositories/bulk').data.decode()
    assert 'value="add_collaborator" data-needs="collaborator"' in html and 'id="loginField"' in html
    html = logged_in_client.post('/repositories/bulk/confirm', data={
        'action': 'remove_collaborator', 'repos': ['alice/app'], 'login': 'bob'}).data.decode()
    assert "Remove bob&#39;s access" in html and 'name="login" value="bob"' in html
