"""Tests for creating repositories from a form (issue #38). GitHub is never contacted."""
from urllib.parse import parse_qs, urlparse
import pytest
from werkzeug.datastructures import MultiDict

from app.controllers import auth_controller, repo_creation_controller
from app.controllers.repo_creation_controller import (
    BRANCH_PROTECTION, create_repository, validate_new_repository,
)
from app.routes import auth_routes, repo_creation_routes

OPTIONS = {'gitignore_templates': ['Python', 'Node'], 'licenses': [{'key': 'mit', 'name': 'MIT License'}]}
TEMPLATES = ['alice/template']
LABEL_SOURCES = ['alice/app', 'alice/template']


def validate(owner='alice', owner_type='User', user_login='alice', **form):
    defaults = {'name': 'new-repo', 'visibility': 'private', 'source': 'blank'}
    return validate_new_repository(MultiDict({**defaults, **form}), owner, owner_type, user_login,
                                   TEMPLATES, LABEL_SOURCES, OPTIONS)


# --- Validation --------------------------------------------------------------

def test_minimal_blank_repository():
    spec, error = validate()
    assert error is None
    assert spec == {
        'owner': 'alice', 'owner_type': 'User', 'name': 'new-repo', 'description': '', 'private': True,
        'source': 'blank', 'template': '', 'include_all_branches': False, 'auto_init': False,
        'gitignore': '', 'license': '', 'copy_labels_from': '', 'protect_default_branch': False,
    }


def test_gitignore_or_license_turns_on_initial_commit():
    spec, _ = validate(gitignore='Python', license='mit')
    assert (spec['auto_init'], spec['gitignore'], spec['license']) == (True, 'Python', 'mit')


def test_description_is_collapsed_to_one_line():
    spec, _ = validate(description='  line one\n\nline   two ')
    assert spec['description'] == 'line one line two'


def test_template_repository():
    spec, error = validate(source='template', template='alice/template', include_all_branches='1',
                           visibility='public', copy_labels_from='alice/app', protect_default_branch='1')
    assert error is None
    assert (spec['source'], spec['template'], spec['include_all_branches'], spec['private']) == (
        'template', 'alice/template', True, False)
    assert (spec['copy_labels_from'], spec['protect_default_branch']) == ('alice/app', True)


@pytest.mark.parametrize('form, message', [
    ({'name': ''}, 'Repository names'),
    ({'name': 'has space'}, 'Repository names'),
    ({'name': '..'}, 'Repository names'),
    ({'name': 'a' * 101}, 'Repository names'),
    ({'description': 'x' * 351}, 'at most 350'),
    ({'visibility': 'internal'}, 'public or private'),
    ({'source': 'fork'}, 'how to start'),
    ({'source': 'template', 'template': 'mallory/template'}, 'listed template'),
    ({'gitignore': 'Cobol'}, "Unknown .gitignore"),
    ({'license': 'wtfpl'}, "Unknown license"),
    ({'protect_default_branch': '1'}, 'needs an initial commit'),
    ({'copy_labels_from': 'mallory/labels'}, 'copy labels from'),
])
def test_invalid_forms(form, message):
    spec, error = validate(**form)
    assert spec is None
    assert message in error


def test_cannot_create_in_another_users_account():
    spec, error = validate(owner='bob', owner_type='User', user_login='alice')
    assert spec is None and "Only bob can create" in error


def test_organization_members_can_create_in_the_org():
    spec, error = validate(owner='acme', owner_type='Organization', user_login='alice')
    assert error is None and spec['owner'] == 'acme'


# --- Creation ----------------------------------------------------------------

@pytest.fixture
def api(monkeypatch):
    """Fake github_api: records calls; `responses` maps (method, path) to (data, error)."""
    state = {'calls': [], 'responses': {}}

    def fake(method, path, token, **kwargs):
        state['calls'].append((method, path, token, kwargs.get('json')))
        response = state['responses'].get((method, path))
        if callable(response):
            return response()
        return response if response else ({}, None)

    monkeypatch.setattr(repo_creation_controller, 'github_api', fake)
    return state


CREATED = {'full_name': 'alice/new-repo', 'html_url': 'https://github.com/alice/new-repo', 'default_branch': 'main'}


def spec_for(**form):
    spec, error = validate(**form)
    assert error is None, error
    return spec


def test_blank_user_repository_is_created_with_the_user_token(api):
    api['responses'][('POST', '/user/repos')] = (CREATED, None)

    result = create_repository(spec_for(gitignore='Python', description='Hi'), 'user-token')

    assert api['calls'] == [('POST', '/user/repos', 'user-token', {
        'name': 'new-repo', 'description': 'Hi', 'private': True, 'auto_init': True, 'gitignore_template': 'Python'})]
    assert result == {'ok': True, 'repo': {'full_name': 'alice/new-repo', 'html_url': CREATED['html_url'],
                                           'default_branch': 'main'},
                      'steps': [{'name': 'Create repository', 'ok': True, 'message': 'alice/new-repo'}]}


def test_organization_repository_uses_org_endpoint(api):
    api['responses'][('POST', '/orgs/acme/repos')] = ({**CREATED, 'full_name': 'acme/new-repo'}, None)
    spec, _ = validate(owner='acme', owner_type='Organization')

    assert create_repository(spec, 'tok')['ok']
    assert api['calls'][0][1] == '/orgs/acme/repos'


def test_template_repository_is_generated(api):
    api['responses'][('POST', '/repos/alice/template/generate')] = (CREATED, None)

    create_repository(spec_for(source='template', template='alice/template', include_all_branches='1'), 'tok')

    assert api['calls'] == [('POST', '/repos/alice/template/generate', 'tok', {
        'owner': 'alice', 'name': 'new-repo', 'description': '', 'private': True, 'include_all_branches': True})]


def test_failed_creation_skips_setup(api):
    api['responses'][('POST', '/user/repos')] = (None, 'name already exists on this account')

    result = create_repository(spec_for(copy_labels_from='alice/app', auto_init='1', protect_default_branch='1'), 'tok')

    assert result == {'ok': False, 'repo': None, 'steps': [
        {'name': 'Create repository', 'ok': False, 'message': 'name already exists on this account'}]}
    assert len(api['calls']) == 1


def test_labels_are_copied_and_existing_ones_updated(api):
    api['responses'].update({
        ('POST', '/user/repos'): (CREATED, None),
        ('GET', '/repos/alice/app/labels'): ([
            {'name': 'needs triage', 'color': 'fbca04', 'description': 'New'},
            {'name': 'bug', 'color': 'd73a4a', 'description': None},
        ], None),
        ('POST', '/repos/alice/new-repo/labels'): lambda: (
            (None, 'Validation Failed') if api['calls'][-1][3]['name'] == 'bug' else ({}, None)),
    })

    result = create_repository(spec_for(copy_labels_from='alice/app'), 'tok')

    assert result['steps'][1] == {'name': 'Copy labels from alice/app', 'ok': True, 'message': '1 created, 1 updated'}
    assert ('PATCH', '/repos/alice/new-repo/labels/bug', 'tok',
            {'name': 'bug', 'color': 'd73a4a', 'description': ''}) in api['calls']


def test_default_branch_protection(api):
    api['responses'][('POST', '/user/repos')] = (CREATED, None)

    result = create_repository(spec_for(auto_init='1', protect_default_branch='1'), 'tok')

    assert ('PUT', '/repos/alice/new-repo/branches/main/protection', 'tok', BRANCH_PROTECTION) in api['calls']
    assert result['ok'] and result['steps'][1]['name'] == "Protect 'main'"


def test_protection_retries_while_template_repo_is_being_generated(api):
    attempts = []
    api['responses'].update({
        ('POST', '/repos/alice/template/generate'): (CREATED, None),
        ('PUT', '/repos/alice/new-repo/branches/main/protection'): lambda: (
            attempts.append(1) or ((None, 'Branch not found') if len(attempts) < 3 else ({}, None))),
    })
    sleeps = []

    result = create_repository(spec_for(source='template', template='alice/template', protect_default_branch='1'),
                               'tok', sleep=sleeps.append)

    assert len(attempts) == 3 and sleeps == [2, 2]
    assert result['ok']


def test_protection_failure_is_reported_but_repo_still_created(api):
    api['responses'].update({
        ('POST', '/user/repos'): (CREATED, None),
        ('PUT', '/repos/alice/new-repo/branches/main/protection'): (
            None, 'Upgrade to GitHub Pro or make this repository public to enable this feature.'),
    })

    result = create_repository(spec_for(auto_init='1', protect_default_branch='1'), 'tok', sleep=lambda s: None)

    assert result['ok'] is False
    assert result['repo']['full_name'] == 'alice/new-repo'
    assert 'Upgrade to GitHub Pro' in result['steps'][1]['message']
    assert sum(1 for call in api['calls'] if call[0] == 'PUT') == 1  # not a "not found" error: no retry


# --- OAuth state purpose -----------------------------------------------------

def test_state_remembers_its_purpose(app):
    with app.test_request_context():
        state = auth_controller.generate_oauth_state(auth_controller.OAUTH_PURPOSE_CREATE_REPOSITORY)
        assert auth_controller.validate_oauth_state(state) == 'create_repository'
        assert auth_controller.validate_oauth_state(state) is None  # single use


def test_state_without_purpose_defaults_to_login(app):
    from flask import session
    with app.test_request_context():
        session['oauth_state'] = 'abc'
        assert auth_controller.validate_oauth_state('abc') == 'login'


# --- Routes ------------------------------------------------------------------

@pytest.mark.parametrize('method, url', [
    ('get', '/repositories/new'), ('post', '/repositories/new'), ('get', '/repositories/new/result'),
])
def test_routes_require_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


@pytest.fixture
def form_data(monkeypatch):
    monkeypatch.setattr(repo_creation_routes, 'get_installation_access_token', lambda: 'installation-token')
    monkeypatch.setattr(repo_creation_routes, 'get_github_repositories', lambda token: [
        {'full_name': 'alice/app'}, {'full_name': 'alice/template', 'is_template': True}])
    monkeypatch.setattr(repo_creation_routes, 'get_form_options', lambda token: OPTIONS)


def _session(client):
    with client.session_transaction() as sess:
        return dict(sess)


def test_form_lists_templates_gitignores_licenses_and_label_sources(logged_in_client, form_data):
    html = logged_in_client.get('/repositories/new').data.decode()
    assert 'value="alice/template"' in html
    assert 'value="Python"' in html and 'MIT License' in html
    assert "Don't copy labels" in html and 'value="alice/app"' in html


def test_invalid_form_is_shown_again_with_values(logged_in_client, form_data):
    response = logged_in_client.post('/repositories/new', data={
        'name': 'bad name', 'description': 'keep me', 'visibility': 'private', 'source': 'blank'})
    assert response.status_code == 400
    assert b'Repository names use letters' in response.data
    assert b'value="keep me"' in response.data
    assert 'pending_repository' not in _session(logged_in_client)


def test_valid_form_sends_user_through_github_authorization(logged_in_client, form_data):
    response = logged_in_client.post('/repositories/new', data={
        'name': 'new-repo', 'visibility': 'public', 'source': 'blank', 'auto_init': '1'})

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers['Location']).query)
    session = _session(logged_in_client)
    assert query['state'] == [session['oauth_state']]
    assert session['oauth_purpose'] == 'create_repository'
    assert session['pending_repository']['name'] == 'new-repo'
    assert session['github_user_login'] == 'alice'  # still signed in


@pytest.fixture
def oauth(monkeypatch):
    monkeypatch.setattr(auth_routes, 'exchange_code_for_user_token', lambda code, uri: 'user-token')
    monkeypatch.setattr(auth_routes, 'get_authenticated_user', lambda token: {'login': 'alice'})
    monkeypatch.setattr(auth_routes, 'get_user_installations',
                        lambda token: pytest.fail("creation must not change the installation"))
    created = []
    monkeypatch.setattr(repo_creation_routes, 'create_repository', lambda spec, token: created.append((spec, token)) or {
        'ok': True, 'repo': {'full_name': 'alice/new-repo', 'html_url': 'https://github.com/alice/new-repo',
                             'default_branch': 'main'},
        'steps': [{'name': 'Create repository', 'ok': True, 'message': 'alice/new-repo'}]})
    return created


def _pending(client, **extra):
    spec, _ = validate()
    with client.session_transaction() as sess:
        sess.update({'oauth_state': 's', 'oauth_purpose': 'create_repository', 'pending_repository': spec, **extra})
    return spec


def test_callback_creates_repository_with_user_token_and_shows_result(logged_in_client, oauth):
    spec = _pending(logged_in_client)

    response = logged_in_client.get('/github/callback?code=c&state=s')

    assert oauth == [(spec, 'user-token')]
    assert response.headers['Location'].endswith('/repositories/new/result')
    session = _session(logged_in_client)
    assert 'pending_repository' not in session
    assert session['installation_id'] == 1  # still signed in with the same installation

    html = logged_in_client.get('/repositories/new/result').data.decode()
    assert 'Repository created' in html and 'alice/new-repo' in html
    assert 'https://github.com/settings/installations/1' in html
    # The result is shown once; refreshing goes back to the form
    assert logged_in_client.get('/repositories/new/result').status_code == 302


def test_callback_refuses_a_different_github_account(logged_in_client, oauth, monkeypatch):
    monkeypatch.setattr(auth_routes, 'get_authenticated_user', lambda token: {'login': 'mallory'})
    _pending(logged_in_client)

    assert logged_in_client.get('/github/callback?code=c&state=s').status_code == 403
    assert oauth == []


def test_callback_without_pending_request(logged_in_client, oauth):
    with logged_in_client.session_transaction() as sess:
        sess.update({'oauth_state': 's', 'oauth_purpose': 'create_repository'})

    response = logged_in_client.get('/github/callback?code=c&state=s')

    assert response.headers['Location'].endswith('/repositories/new')
    assert oauth == []


def test_org_result_links_to_org_installation_settings(logged_in_client, oauth):
    with logged_in_client.session_transaction() as sess:
        sess.update({'github_account_type': 'Organization', 'github_username': 'acme',
                     'repository_creation_result': {'ok': True, 'steps': [], 'repo': {
                         'full_name': 'acme/x', 'html_url': 'https://github.com/acme/x', 'default_branch': 'main'}}})
    html = logged_in_client.get('/repositories/new/result').data.decode()
    assert 'https://github.com/organizations/acme/settings/installations/1' in html
