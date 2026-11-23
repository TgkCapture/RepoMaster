"""Tests for GitHub sign-in (OAuth) and installation verification (issue #49)."""
from urllib.parse import urlparse, parse_qs
import pytest

from app import create_app
from app.config.production_config import ProductionConfig
from app.controllers import auth_controller
from app.routes import auth_routes

ALICE = {'login': 'alice', 'avatar_url': 'https://example.com/alice.png'}
ALICE_INSTALLATION = {'id': 7, 'account': {'login': 'alice'}}
ORG_INSTALLATION = {'id': 5, 'account': {'login': 'some-org'}}


@pytest.fixture
def github(monkeypatch):
    """Fake the GitHub OAuth/user API calls made during the callback."""
    fake = {
        'token': 'user-token',
        'user': ALICE,
        'installations': [ORG_INSTALLATION, ALICE_INSTALLATION],
        'exchanged_codes': [],
    }

    def exchange(code, redirect_uri):
        fake['exchanged_codes'].append(code)
        return fake['token']

    monkeypatch.setattr(auth_routes, 'exchange_code_for_user_token', exchange)
    monkeypatch.setattr(auth_routes, 'get_authenticated_user', lambda token: fake['user'])
    monkeypatch.setattr(auth_routes, 'get_user_installations', lambda token: fake['installations'])
    return fake


def _set_state(client, state='known-state', **extra):
    with client.session_transaction() as sess:
        sess['oauth_state'] = state
        sess.update(extra)


def _session(client):
    with client.session_transaction() as sess:
        return dict(sess)


# --- The original vulnerability ----------------------------------------------

def test_installation_id_in_url_does_not_log_anyone_in(client):
    response = client.get('/github/authorize?installation_id=999')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/login')
    session = _session(client)
    assert 'installation_id' not in session
    assert session['pending_installation_id'] == '999'
    assert client.get('/github/repositories').status_code == 403


def test_pending_installation_the_user_cannot_access_is_refused(client, github):
    _set_state(client, pending_installation_id='999')

    response = client.get('/github/callback?code=abc&state=known-state')

    assert response.status_code == 403
    assert 'installation_id' not in _session(client)
    assert client.get('/github/repositories').status_code == 403


# --- /login ------------------------------------------------------------------

def test_login_redirects_to_github_with_one_time_state(client):
    response = client.get('/login')

    location = urlparse(response.headers['Location'])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}" == auth_controller.OAUTH_AUTHORIZE_URL
    assert query['client_id'] == ['test-client-id']
    assert query['redirect_uri'] == ['http://localhost/github/callback']
    assert query['state'] == [_session(client)['oauth_state']]


def test_login_uses_configured_callback_url(app, client):
    app.config['GITHUB_OAUTH_CALLBACK_URL'] = 'https://repomaster.example/github/callback'
    query = parse_qs(urlparse(client.get('/login').headers['Location']).query)
    assert query['redirect_uri'] == ['https://repomaster.example/github/callback']


def test_login_without_client_id_is_a_config_error(app, client):
    app.config['GITHUB_CLIENT_ID'] = None
    assert client.get('/login').status_code == 500


# --- /github/callback --------------------------------------------------------

@pytest.mark.parametrize('query', [
    'code=abc',                     # no state
    'code=abc&state=wrong-state',   # forged state
])
def test_callback_rejects_bad_state(client, github, query):
    _set_state(client)
    assert client.get(f'/github/callback?{query}').status_code == 400
    assert github['exchanged_codes'] == []


def test_callback_without_issued_state_is_rejected(client, github):
    assert client.get('/github/callback?code=abc&state=anything').status_code == 400


def test_state_can_only_be_used_once(client, github):
    _set_state(client)
    client.get('/github/callback?code=abc&state=known-state')
    client.get('/logout')

    assert client.get('/github/callback?code=abc&state=known-state').status_code == 400


def test_successful_sign_in_prefers_the_users_own_installation(client, github):
    _set_state(client)

    response = client.get('/github/callback?code=abc&state=known-state')

    assert response.status_code == 302
    session = _session(client)
    assert session['github_user_login'] == 'alice'
    assert session['installation_id'] == 7
    assert session['github_username'] == 'alice'
    assert 'oauth_state' not in session
    assert github['exchanged_codes'] == ['abc']


def test_sign_in_uses_pending_installation_when_user_can_access_it(client, github):
    _set_state(client, pending_installation_id='5')

    client.get('/github/callback?code=abc&state=known-state')

    session = _session(client)
    assert session['installation_id'] == 5
    assert session['github_username'] == 'some-org'
    assert 'pending_installation_id' not in session


def test_sign_in_replaces_stale_session_data(client, github):
    _set_state(client, installation_id='999', github_username='mallory', leftover='x')

    client.get('/github/callback?code=abc&state=known-state')

    session = _session(client)
    assert session['installation_id'] == 7
    assert 'leftover' not in session


def test_sign_in_with_no_installations_sends_user_to_install(client, github):
    github['installations'] = []
    _set_state(client)

    response = client.get('/github/callback?code=abc&state=known-state')

    assert response.headers['Location'].endswith('/github/install')
    assert 'installation_id' not in _session(client)


def test_failed_code_exchange_does_not_sign_in(client, github):
    github['token'] = None
    _set_state(client)

    assert client.get('/github/callback?code=abc&state=known-state').status_code == 500
    assert 'github_user_login' not in _session(client)


def test_cancelled_sign_in_returns_home(client, github):
    response = client.get('/github/callback?error=access_denied&state=x')
    assert response.status_code == 302
    assert github['exchanged_codes'] == []


def test_signed_in_message_is_shown_on_home_page(client, github):
    _set_state(client)
    response = client.get('/github/callback?code=abc&state=known-state', follow_redirects=True)
    assert b'Signed in as alice.' in response.data
    assert b'Log Out' in response.data


# --- /github/authorize (Setup URL) --------------------------------------------

def test_org_installation_request_goes_home(client):
    response = client.get('/github/authorize?setup_action=request')
    assert response.headers['Location'].endswith('/')
    assert 'pending_installation_id' not in _session(client)


# --- Controller helpers ------------------------------------------------------

class FakeResponse:
    def __init__(self, json_data, status_code=200):
        self._json = json_data
        self.status_code = status_code

    def json(self):
        return self._json

    def raise_for_status(self):
        pass


def test_code_exchange_treats_error_payload_as_failure(app, monkeypatch):
    monkeypatch.setattr(auth_controller.requests, 'post',
                        lambda *a, **k: FakeResponse({'error': 'bad_verification_code'}))
    with app.test_request_context():
        assert auth_controller.exchange_code_for_user_token('abc', 'http://localhost/github/callback') is None


def test_code_exchange_returns_token(app, monkeypatch):
    sent = {}

    def fake_post(url, data, headers, timeout):
        sent.update(url=url, data=data)
        return FakeResponse({'access_token': 'ghu_token'})

    monkeypatch.setattr(auth_controller.requests, 'post', fake_post)
    with app.test_request_context():
        token = auth_controller.exchange_code_for_user_token('abc', 'http://localhost/github/callback')

    assert token == 'ghu_token'
    assert sent['url'] == auth_controller.OAUTH_TOKEN_URL
    assert sent['data']['client_secret'] == 'test-client-secret'


@pytest.mark.parametrize('installations, requested, expected_id', [
    ([ORG_INSTALLATION, ALICE_INSTALLATION], None, 7),   # prefer the user's own account
    ([ORG_INSTALLATION], None, 5),                       # otherwise the first one
    ([], None, None),
    ([ORG_INSTALLATION, ALICE_INSTALLATION], '5', 5),     # requested and accessible
    ([ORG_INSTALLATION, ALICE_INSTALLATION], '999', None),  # requested but not accessible
])
def test_choose_installation(installations, requested, expected_id):
    chosen = auth_controller.choose_installation(installations, 'alice', requested)
    assert (chosen or {}).get('id') == expected_id


def test_production_requires_oauth_credentials(monkeypatch):
    for name in ('SECRET_KEY', 'GITHUB_APP_ID', 'GITHUB_APP_NAME', 'GITHUB_PRIVATE_KEY_PATH'):
        monkeypatch.setattr(ProductionConfig, name, 'set')
    monkeypatch.setattr(ProductionConfig, 'GITHUB_CLIENT_ID', None)
    monkeypatch.setattr(ProductionConfig, 'GITHUB_CLIENT_SECRET', None)

    with pytest.raises(RuntimeError, match='GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET'):
        create_app('production')
