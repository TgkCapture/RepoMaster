"""Tests for switching between installations (issue #50). GitHub is never contacted."""
import pytest

from app.controllers import repo_controller
from app.controllers.auth_controller import (
    MAX_SWITCHABLE_INSTALLATIONS, account_avatar_url, choose_installation, summarize_installations,
)
from app.routes import auth_routes, repo_routes

ALICE = {'login': 'alice', 'avatar_url': 'https://example.com/alice.png'}
INSTALLATIONS = [
    {'id': 5, 'account': {'login': 'zeta-org', 'id': 500, 'type': 'Organization'}},
    {'id': 7, 'account': {'login': 'alice', 'id': 700, 'type': 'User'}},
    {'id': 9, 'account': {'login': 'acme', 'id': 900, 'type': 'Organization'}},
]


@pytest.fixture
def github(monkeypatch):
    fake = {'installations': list(INSTALLATIONS)}
    monkeypatch.setattr(auth_routes, 'exchange_code_for_user_token', lambda code, uri: 'user-token')
    monkeypatch.setattr(auth_routes, 'get_authenticated_user', lambda token: ALICE)
    monkeypatch.setattr(auth_routes, 'get_user_installations', lambda token: fake['installations'])
    return fake


def sign_in(client, **session_extra):
    with client.session_transaction() as sess:
        sess['oauth_state'] = 'st'
        sess.update(session_extra)
    return client.get('/github/callback?code=abc&state=st')


def session_of(client):
    with client.session_transaction() as sess:
        return dict(sess)


# --- Installation list -------------------------------------------------------

def test_summarize_installations_puts_own_account_first():
    rows = summarize_installations(INSTALLATIONS + [{'id': 1, 'account': {}}, {'account': {'login': 'x'}}], 'Alice')
    assert rows == [
        {'id': 7, 'login': 'alice', 'type': 'User', 'account_id': 700},
        {'id': 9, 'login': 'acme', 'type': 'Organization', 'account_id': 900},
        {'id': 5, 'login': 'zeta-org', 'type': 'Organization', 'account_id': 500},
    ]


def test_summarize_installations_is_capped():
    many = [{'id': i, 'account': {'login': f'org{i:03}', 'id': i}} for i in range(100)]
    assert len(summarize_installations(many, 'alice')) == MAX_SWITCHABLE_INSTALLATIONS


def test_avatar_url():
    assert account_avatar_url(900, 40) == 'https://avatars.githubusercontent.com/u/900?s=40&v=4'
    assert account_avatar_url(None) is None


def test_choose_installation_keeps_previous_when_still_available():
    assert choose_installation(INSTALLATIONS, 'alice', previous_installation_id=9)['id'] == 9
    assert choose_installation(INSTALLATIONS, 'alice', previous_installation_id=404)['id'] == 7
    # A requested installation (just installed) still wins
    assert choose_installation(INSTALLATIONS, 'alice', '5', previous_installation_id=9)['id'] == 5


def test_sign_in_stores_verified_installations(client, github):
    sign_in(client)
    session = session_of(client)
    assert session['installation_id'] == 7 and session['github_username'] == 'alice'
    assert [entry['id'] for entry in session['installations']] == [7, 9, 5]


def test_signing_in_again_keeps_the_active_account(client, github):
    sign_in(client, github_user_login='alice', installation_id=9)
    assert session_of(client)['installation_id'] == 9


def test_signing_in_as_someone_else_does_not_inherit_the_account(client, github):
    sign_in(client, github_user_login='mallory', installation_id=9)
    assert session_of(client)['installation_id'] == 7


# --- Switching ---------------------------------------------------------------

@pytest.fixture
def signed_in(client, github):
    sign_in(client)
    return client


def test_switch_to_organization(signed_in):
    with signed_in.session_transaction() as sess:
        sess['pending_repository'] = {'name': 'half-made'}
    response = signed_in.post('/accounts/switch', data={'installation_id': '9'})
    assert response.status_code == 302 and response.headers['Location'] == '/github/repositories'
    session = session_of(signed_in)
    assert session['installation_id'] == 9 and session['github_username'] == 'acme'
    assert session['github_account_type'] == 'Organization'
    assert session['github_user_login'] == 'alice'  # still the same person
    assert 'pending_repository' not in session


@pytest.mark.parametrize('installation_id', ['12345', '', 'abc'])
def test_cannot_switch_to_unverified_installation(signed_in, installation_id):
    response = signed_in.post('/accounts/switch', data={'installation_id': installation_id}, follow_redirects=True)
    assert "That account isn&#39;t available to you" in response.data.decode()
    assert session_of(signed_in)['installation_id'] == 7


def test_accounts_page_lists_accounts(signed_in):
    html = signed_in.get('/accounts').data.decode()
    assert html.count('name="installation_id"') == 2  # every account except the active one
    assert 'Managing</span>' in html and 'acme' in html and 'zeta-org' in html
    assert 'https://avatars.githubusercontent.com/u/900?s=64&amp;v=4' in html
    assert 'Install on another account' in html


def test_old_session_without_list_still_works(logged_in_client):
    html = logged_in_client.get('/accounts').data.decode()
    assert 'Sign in again to load your accounts.' in html
    assert logged_in_client.post('/accounts/switch', data={'installation_id': '1'}).status_code == 302


def test_switcher_shows_active_account(signed_in, monkeypatch):
    monkeypatch.setattr(repo_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(repo_routes, 'get_github_repositories', lambda token: [])
    signed_in.post('/accounts/switch', data={'installation_id': '9'})
    html = signed_in.get('/github/repositories').data.decode()
    assert 'id="accountSwitcher"' in html and 'title="Managing acme. Switch account"' in html
    assert 'Account: acme' in signed_in.get('/').data.decode()


def test_switcher_hidden_when_signed_out(client):
    assert b'Account:' not in client.get('/').data


@pytest.mark.parametrize('method, url', [('get', '/accounts'), ('post', '/accounts/switch')])
def test_requires_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


# --- Repository list ---------------------------------------------------------

class FakeResponse:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data

    def raise_for_status(self):
        pass


def test_repositories_are_fetched_across_pages(app, monkeypatch):
    pages = []

    def fake_get(url, headers, params, timeout):
        pages.append(params['page'])
        count = 100 if params['page'] < 3 else 20
        return FakeResponse({'total_count': 220, 'repositories': [{'name': f'r{params["page"]}-{i}', 'language': None}
                                                                   for i in range(count)]})

    monkeypatch.setattr(repo_controller.requests, 'get', fake_get)
    repositories = repo_controller.get_github_repositories('tok')
    assert pages == [1, 2, 3] and len(repositories) == 220


def test_repository_paging_stops_at_total_and_limit(app, monkeypatch):
    pages = []

    def fake_get(url, headers, params, timeout):
        pages.append(params['page'])
        return FakeResponse({'total_count': 5000, 'repositories': [{'name': 'r', 'language': None}] * 100})

    monkeypatch.setattr(repo_controller.requests, 'get', fake_get)
    assert len(repo_controller.get_github_repositories('tok')) == 100 * repo_controller.MAX_REPOSITORY_PAGES
    assert len(pages) == repo_controller.MAX_REPOSITORY_PAGES
