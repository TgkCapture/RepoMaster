"""Tests for the JSON API, API tokens and the API docs (issue #53). GitHub is never contacted."""
import base64
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from app.controllers import api_controller, api_token_controller
from app.controllers.api_controller import file_summary, validate_ref
from app.controllers.api_token_controller import (
    MAX_ACTIVE_TOKENS, authenticate_token, create_token, hash_token, list_tokens, revoke_token,
)
from app.db import get_db
from app.routes import api_routes

REPOS = [
    {'id': 1, 'name': 'api', 'full_name': 'alice/api', 'owner': {'login': 'alice'}, 'description': 'Backend',
     'private': True, 'visibility': 'private', 'fork': False, 'archived': False, 'language': 'Python',
     'stargazers_count': 3, 'forks_count': 1, 'open_issues_count': 2, 'default_branch': 'main',
     'html_url': 'https://github.com/alice/api', 'updated_at': '2026-11-20T00:00:00Z', 'pushed_at': None},
    {'id': 2, 'name': 'site', 'full_name': 'alice/site', 'owner': {'login': 'alice'}, 'description': None,
     'private': False, 'fork': False, 'archived': True, 'language': 'HTML', 'stargazers_count': 9,
     'updated_at': '2026-10-01T00:00:00Z'},
]


@pytest.fixture
def token(app):
    """A valid token for installation 1 (account alice)."""
    with app.app_context():
        value, error = create_token(1, 'alice', 'User', 'alice', 'CI script')
    assert error is None
    return value


@pytest.fixture
def github(monkeypatch):
    """Fake GitHub: records calls, answers from `responses` keyed by function name."""
    state = {'calls': [], 'tokens': [], 'responses': {}}

    def fake(name):
        def call(*args, **kwargs):
            state['calls'].append((name, args))
            return state['responses'].get(name, (None, 'Not Found'))
        return call

    def installation_token(installation_id=None):
        state['tokens'].append(installation_id)
        return 'gh-installation-token'

    monkeypatch.setattr(api_routes, 'get_installation_access_token', installation_token)
    monkeypatch.setattr(api_routes, 'get_github_repositories', lambda t: state['responses'].get('repos', REPOS))
    for name in ('get_repository', 'list_issues', 'list_pull_requests', 'list_branches'):
        monkeypatch.setattr(api_routes, name, fake(name))
    monkeypatch.setattr(api_controller, 'github_api', fake('github_api'))
    return state


def get(client, url, token=None, **headers):
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return client.get(url, headers=headers)


# --- Tokens ------------------------------------------------------------------

def test_created_token_is_stored_hashed(app, token):
    assert token.startswith('rm_') and len(token) > 40
    with app.app_context():
        row = get_db().execute('SELECT * FROM api_tokens').fetchone()
    assert row['token_hash'] == hash_token(token)
    assert token not in dict(row).values()
    assert row['prefix'] == token[:10]
    assert (row['installation_id'], row['account'], row['created_by'], row['name']) == (1, 'alice', 'alice', 'CI script')


def test_token_names_are_validated(app):
    with app.app_context():
        assert create_token(1, 'alice', 'User', 'alice', '   ')[1]
        assert create_token(1, 'alice', 'User', 'alice', 'x' * 61)[1]
        assert create_token(1, 'alice', 'User', 'alice', '  my   tool ')[1] is None
        assert list_tokens(1)[0]['name'] == 'my tool'


def test_active_token_limit(app):
    with app.app_context():
        for n in range(MAX_ACTIVE_TOKENS):
            assert create_token(1, 'alice', 'User', 'alice', f't{n}')[1] is None
        assert 'Revoke one first' in create_token(1, 'alice', 'User', 'alice', 'one more')[1]
        assert create_token(2, 'acme', 'Organization', 'alice', 'other account')[1] is None
        revoke_token(list_tokens(1)[0]['id'], 1)
        assert create_token(1, 'alice', 'User', 'alice', 'now fits')[1] is None


def test_authenticate_and_revoke(app, token):
    with app.app_context():
        record = authenticate_token(token)
        assert record['installation_id'] == 1 and record['account'] == 'alice'
        assert authenticate_token(token + 'x') is None
        assert authenticate_token('not-a-token') is None
        assert authenticate_token('') is None
        assert revoke_token(record['id'], 2) is False  # another installation can't revoke it
        assert revoke_token(record['id'], 1) is True
        assert revoke_token(record['id'], 1) is False
        assert authenticate_token(token) is None


def test_last_used_is_updated_at_most_once_a_minute(app, token):
    now = datetime(2026, 11, 28, 12, 0, tzinfo=timezone.utc)
    with app.app_context():
        authenticate_token(token, now=now)
        assert list_tokens(1)[0]['last_used_at'] == '2026-11-28T12:00:00Z'
        authenticate_token(token, now=now + timedelta(seconds=30))
        assert list_tokens(1)[0]['last_used_at'] == '2026-11-28T12:00:00Z'
        authenticate_token(token, now=now + timedelta(minutes=2))
        assert list_tokens(1)[0]['last_used_at'] == '2026-11-28T12:02:00Z'


# --- Authentication on the API --------------------------------------------------

@pytest.mark.parametrize('headers', [{}, {'Authorization': 'Basic abc'}, {'Authorization': 'Bearer '},
                                     {'Authorization': 'Bearer rm_wrong'}])
def test_api_requires_a_valid_token(client, github, headers):
    response = client.get('/api/v1/repos', headers=headers)
    assert response.status_code == 401
    assert response.headers['WWW-Authenticate'].startswith('Bearer')
    assert response.get_json()['error']['status'] == 401
    assert github['tokens'] == []


def test_api_ignores_the_browser_session(logged_in_client, github):
    """A signed-in user's cookies are not enough: the API only accepts tokens."""
    assert logged_in_client.get('/api/v1/me').status_code == 401


def test_revoked_token_stops_working(app, client, token, github):
    assert get(client, '/api/v1/me', token).status_code == 200
    with app.app_context():
        revoke_token(list_tokens(1)[0]['id'], 1)
    assert get(client, '/api/v1/me', token).status_code == 401


def test_me(client, token, github):
    response = get(client, '/api/v1/me', token)
    assert response.get_json() == {'account': 'alice', 'account_type': 'User', 'installation_id': 1,
                                   'token': {'name': 'CI script', 'created_by': 'alice'}}
    assert response.headers['Cache-Control'] == 'no-store'
    assert github['tokens'] == []  # no GitHub call needed


def test_bearer_scheme_is_case_insensitive(client, token, github):
    assert client.get('/api/v1/me', headers={'Authorization': f'bearer {token}'}).status_code == 200


# --- Endpoints -----------------------------------------------------------------

def test_list_repositories(client, token, github):
    data = get(client, '/api/v1/repos', token).get_json()
    assert (data['total'], data['matching'], data['page'], data['pages'], data['per_page']) == (2, 2, 1, 1, 30)
    assert [r['full_name'] for r in data['items']] == ['alice/api', 'alice/site']
    assert data['items'][0] == {
        'id': 1, 'name': 'api', 'full_name': 'alice/api', 'owner': 'alice', 'description': 'Backend',
        'private': True, 'visibility': 'private', 'fork': False, 'archived': False, 'language': 'Python',
        'stars': 3, 'forks': 1, 'open_issues': 2, 'default_branch': 'main',
        'html_url': 'https://github.com/alice/api', 'updated_at': '2026-11-20T00:00:00Z', 'pushed_at': None}
    assert data['items'][1]['visibility'] == 'public'
    assert github['tokens'] == [1]  # the token's installation


def test_list_repositories_filters_and_pages(client, token, github):
    data = get(client, '/api/v1/repos?status=archived&sort=stars', token).get_json()
    assert [r['name'] for r in data['items']] == ['site']
    assert data['filters']['status'] == 'archived'
    data = get(client, '/api/v1/repos?sort=name&per_page=1&page=2', token).get_json()
    assert [r['name'] for r in data['items']] == ['site'] and data['pages'] == 2


@pytest.mark.parametrize('query', ['per_page=0', 'per_page=101', 'per_page=abc', 'page=0'])
def test_list_repositories_rejects_bad_paging(client, token, github, query):
    response = get(client, f'/api/v1/repos?{query}', token)
    assert response.status_code == 400
    assert response.get_json()['error']['message']


def test_list_repositories_github_failure(client, token, github):
    github['responses']['repos'] = None
    assert get(client, '/api/v1/repos', token).status_code == 502


def test_get_repository(client, token, github):
    github['responses']['get_repository'] = (REPOS[0], None)
    data = get(client, '/api/v1/repos/alice/api', token).get_json()
    assert data['full_name'] == 'alice/api'
    assert github['calls'] == [('get_repository', ('alice', 'api', 'gh-installation-token'))]


def test_owner_is_case_insensitive(client, token, github):
    github['responses']['get_repository'] = (REPOS[0], None)
    assert get(client, '/api/v1/repos/ALICE/api', token).status_code == 200


@pytest.mark.parametrize('url', ['/api/v1/repos/bob/api', '/api/v1/repos/bob/api/issues',
                                 '/api/v1/repos/bob/api/contents/README.md', '/api/v1/repos/alice/..'])
def test_other_accounts_repositories_are_not_served(client, token, github, url):
    response = get(client, url, token)
    assert response.status_code == 404
    assert github['calls'] == [] and github['tokens'] == []


def test_github_not_found_and_errors(client, token, github):
    assert get(client, '/api/v1/repos/alice/missing', token).status_code == 404
    github['responses']['get_repository'] = (None, 'Bad credentials')
    response = get(client, '/api/v1/repos/alice/api', token)
    assert response.status_code == 502
    assert 'Bad credentials' in response.get_json()['error']['message']


def test_installation_token_failure(client, token, github, monkeypatch):
    monkeypatch.setattr(api_routes, 'get_installation_access_token', lambda installation_id: None)
    response = get(client, '/api/v1/repos', token)
    assert response.status_code == 502
    assert 'installed' in response.get_json()['error']['message']


def test_list_issues(client, token, github):
    github['responses']['list_issues'] = ([{
        'number': 7, 'title': 'Bug', 'state': 'open', 'user': {'login': 'bob'},
        'labels': [{'name': 'bug'}], 'assignees': [{'login': 'alice'}], 'comments': 2,
        'created_at': '2026-11-01T00:00:00Z', 'updated_at': '2026-11-02T00:00:00Z', 'closed_at': None,
        'html_url': 'https://github.com/alice/api/issues/7', 'body': 'secret details not exposed'}], None)
    data = get(client, '/api/v1/repos/alice/api/issues?state=closed', token).get_json()
    assert data == {'count': 1, 'items': [{
        'number': 7, 'title': 'Bug', 'state': 'open', 'author': 'bob', 'labels': ['bug'], 'assignees': ['alice'],
        'comments': 2, 'created_at': '2026-11-01T00:00:00Z', 'updated_at': '2026-11-02T00:00:00Z',
        'closed_at': None, 'html_url': 'https://github.com/alice/api/issues/7'}]}
    assert github['calls'][0][1][3] == 'closed'


def test_issue_state_defaults_to_open(client, token, github):
    github['responses']['list_issues'] = ([], None)
    get(client, '/api/v1/repos/alice/api/issues?state=weird', token)
    assert github['calls'][0][1][3] == 'open'


def test_list_pull_requests(client, token, github):
    github['responses']['list_pull_requests'] = ([{
        'number': 3, 'title': 'Feature', 'state': 'open', 'draft': True, 'user': {'login': 'bob'},
        'head': {'ref': 'feat'}, 'base': {'ref': 'main'}, 'merged_at': None}], None)
    item = get(client, '/api/v1/repos/alice/api/pulls', token).get_json()['items'][0]
    assert (item['number'], item['draft'], item['author'], item['head'], item['base']) == (3, True, 'bob', 'feat', 'main')


def test_list_branches(client, token, github):
    github['responses']['list_branches'] = ([{'name': 'main', 'protected': True, 'commit': {'sha': 'abc'}}], None)
    assert get(client, '/api/v1/repos/alice/api/branches', token).get_json() == {
        'count': 1, 'items': [{'name': 'main', 'protected': True, 'sha': 'abc'}]}


def test_directory_contents(client, token, github):
    github['responses']['github_api'] = ([
        {'name': 'b.py', 'path': 'src/b.py', 'type': 'file', 'size': 10, 'sha': '1'},
        {'name': 'lib', 'path': 'src/lib', 'type': 'dir', 'size': 0, 'sha': '2'},
        {'name': 'A.md', 'path': 'src/A.md', 'type': 'file', 'size': 5, 'sha': '3'}], None)
    data = get(client, '/api/v1/repos/alice/api/contents/src/?ref=dev', token).get_json()
    assert data['type'] == 'dir' and data['path'] == 'src'
    assert [e['name'] for e in data['entries']] == ['lib', 'A.md', 'b.py']
    name, args = github['calls'][0]
    assert args[1] == '/repos/alice/api/contents/src'


def test_root_contents(client, token, github):
    github['responses']['github_api'] = ([], None)
    data = get(client, '/api/v1/repos/alice/api/contents', token).get_json()
    assert data == {'type': 'dir', 'path': '', 'entries': []}
    assert github['calls'][0][1][1] == '/repos/alice/api/contents/'


def test_text_file_contents(client, token, github):
    github['responses']['github_api'] = ({
        'type': 'file', 'name': 'app.py', 'path': 'app.py', 'sha': 's', 'size': 12, 'encoding': 'base64',
        'content': base64.b64encode('print("hé")\n'.encode()).decode() + '\n',
        'html_url': 'https://github.com/alice/api/blob/main/app.py'}, None)
    data = get(client, '/api/v1/repos/alice/api/contents/app.py', token).get_json()
    assert (data['type'], data['encoding'], data['content']) == ('file', 'utf-8', 'print("hé")\n')


def test_binary_and_large_files():
    binary = base64.b64encode(b'\x89PNG\x00\x01').decode()
    assert file_summary({'type': 'file', 'encoding': 'base64', 'content': binary})[
        'encoding'] == 'base64'
    large = file_summary({'type': 'file', 'encoding': 'none', 'content': '', 'size': 5_000_000})
    assert (large['encoding'], large['content'], large['size']) == (None, None, 5_000_000)


@pytest.mark.parametrize('url', ['/api/v1/repos/alice/api/contents/a/../b', '/api/v1/repos/alice/api/contents/.git/config',
                                 '/api/v1/repos/alice/api/contents?ref=a..b', '/api/v1/repos/alice/api/contents?ref=x%20y'])
def test_contents_rejects_unsafe_input(client, token, github, url):
    assert get(client, url, token).status_code in (400, 404)
    assert [c for c in github['calls'] if c[0] == 'github_api'] == []


def test_validate_ref():
    assert validate_ref('') == (None, None)
    assert validate_ref(' feature/x ') == ('feature/x', None)
    assert validate_ref('v1.0') == ('v1.0', None)
    for bad in ('a..b', 'a b', 'a~1', 'x' * 256, 'a:b'):
        assert validate_ref(bad)[1]


def test_unknown_api_path_and_method_are_json(client, token):
    response = get(client, '/api/v1/nope', token)
    assert response.status_code == 404 and response.get_json()['error']['status'] == 404
    response = client.post('/api/v1/repos', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 405 and 'read-only' in response.get_json()['error']['message']


def test_non_api_404_is_unchanged(client):
    response = client.get('/no-such-page')
    assert response.status_code == 404 and not response.is_json


# --- OpenAPI document and docs page ---------------------------------------------

def load_spec():
    with open(os.path.join(os.path.dirname(__file__), '..', 'OpenAPI.json'), encoding='utf-8') as f:
        return json.load(f)


def test_openapi_is_served_without_a_token(client):
    response = client.get('/api/v1/openapi.json')
    assert response.status_code == 200
    assert response.get_json() == load_spec()


def test_openapi_documents_every_api_route(app):
    spec = load_spec()
    assert spec['servers'] == [{'url': '/api/v1', 'description': 'This RepoMaster server'}]
    assert 'tgkcapture' not in json.dumps(spec['servers'])
    routes = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith('api_v1.'):
            path = rule.rule[len('/api/v1'):]
            for converter in ('<owner>', '<repo>', '<path:path>'):
                path = path.replace(converter, '{' + converter.strip('<>').split(':')[-1] + '}')
            routes.add(path)
    assert routes == set(spec['paths'])
    for path, operations in spec['paths'].items():
        assert set(operations) == {'get'}, path


def test_openapi_schemas_match_the_summaries():
    schemas = load_spec()['components']['schemas']
    assert set(schemas['Repository']['properties']) == set(api_controller.repository_summary({}))
    assert set(schemas['Issue']['properties']) == set(api_controller.issue_summary({}))
    assert set(schemas['PullRequest']['properties']) == set(api_controller.pull_request_summary({}))
    assert set(schemas['Branch']['properties']) == set(api_controller.branch_summary({}))
    assert set(schemas['File']['properties']) == set(file_summary({}))


def test_docs_page_is_public_and_loads_the_spec(client):
    html = client.get('/api/docs').data.decode()
    assert 'swagger-ui-bundle.js' in html
    assert '"/api/v1/openapi.json"' in html


# --- Token pages -----------------------------------------------------------------

def test_token_pages_require_login(client):
    assert client.get('/api/tokens').status_code == 403
    assert client.post('/api/tokens', data={'name': 'x'}).status_code == 403


def test_create_token_shows_it_once(app, logged_in_client):
    response = logged_in_client.post('/api/tokens', data={'name': 'Backup script'})
    html = response.data.decode()
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    shown = html.split('id="newToken" class="form-control font-monospace" value="')[1].split('"')[0]
    assert shown.startswith('rm_')
    with app.app_context():
        assert authenticate_token(shown)['account'] == 'alice'
    with logged_in_client.session_transaction() as sess:
        assert shown not in json.dumps(dict(sess))
    again = logged_in_client.get('/api/tokens').data.decode()
    assert shown not in again and 'Backup script' in again and shown[:10] in again


def test_create_token_rejects_empty_name(logged_in_client):
    response = logged_in_client.post('/api/tokens', data={'name': ' '})
    assert response.status_code == 400
    assert 'Give the token a name' in response.data.decode()


def test_create_token_needs_account(logged_in_client):
    with logged_in_client.session_transaction() as sess:
        del sess['github_username']
    response = logged_in_client.post('/api/tokens', data={'name': 'x'}, follow_redirects=True)
    assert 'log in again' in response.data.decode()


def test_revoke_from_page_and_audit(app, logged_in_client):
    logged_in_client.post('/api/tokens', data={'name': 'Old tool'})
    with app.app_context():
        token_id = list_tokens(1)[0]['id']
    html = logged_in_client.post(f'/api/tokens/{token_id}/revoke', follow_redirects=True).data.decode()
    assert "Token &#39;Old tool&#39; revoked" in html or "Token 'Old tool' revoked" in html
    assert 'Revoked' in html
    html = logged_in_client.post(f'/api/tokens/{token_id}/revoke', follow_redirects=True).data.decode()
    assert 'already revoked' in html
    with app.app_context():
        actions = [row['action'] for row in get_db().execute('SELECT action FROM audit_log ORDER BY id')]
    assert actions == ['api_token.create', 'api_token.revoke']


def test_tokens_are_per_installation(app, logged_in_client):
    with app.app_context():
        create_token(2, 'acme', 'Organization', 'alice', 'Org token')
    html = logged_in_client.get('/api/tokens').data.decode()
    assert 'Org token' not in html
    with app.app_context():
        other_id = list_tokens(2)[0]['id']
    logged_in_client.post(f'/api/tokens/{other_id}/revoke')
    with app.app_context():
        assert list_tokens(2)[0]['revoked_at'] is None


def test_repositories_page_links_to_api(logged_in_client, monkeypatch):
    from app.routes import repo_routes
    monkeypatch.setattr(repo_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(repo_routes, 'get_github_repositories', lambda token: [])
    assert 'href="/api/tokens"' in logged_in_client.get('/github/repositories').data.decode()
