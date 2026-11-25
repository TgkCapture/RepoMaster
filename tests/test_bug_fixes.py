"""Regression tests for bugs fixed after the project restructure.

GitHub is never contacted: controller functions and `requests` calls are patched.
"""
import base64
import pytest
import requests
from flask import session, url_for

from app.controllers import auth_controller, repo_controller
from app.routes import (
    branch_routes, content_routes, issue_routes, pull_request_routes, repo_routes,
)


class FakeResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.text = str(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)


@pytest.fixture
def fake_token(monkeypatch):
    """Make every module that fetches an installation token get a fake one."""
    for module in (repo_controller, repo_routes, branch_routes, pull_request_routes):
        monkeypatch.setattr(module, 'get_installation_access_token', lambda: 'fake-token')


# --- Authentication ----------------------------------------------------------

@pytest.mark.parametrize('method, url', [
    ('get', '/github/repository/alice/repo'),
    ('get', '/github/repository/branch-details?repo_name=repo&branch_name=main'),
    ('get', '/repos/alice/repo/git/refs'),
    ('post', '/repos/alice/repo/branches/main/delete'),
    ('post', '/repos/alice/repo/branches/main/rename'),
    ('get', '/github/repos/alice/repo/contents'),
    ('post', '/github/repos/alice/repo/contents'),
    ('post', '/github/repos/alice/repo/files/update/README.md'),
    ('post', '/github/repos/alice/repo/files/delete/README.md'),
])
def test_routes_that_lacked_login_checks_now_require_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


def test_installation_token_without_installation_id_returns_none(app):
    # Previously the JWT (and private key) was loaded first, raising FileNotFoundError
    with app.test_request_context():
        assert auth_controller.get_installation_access_token() is None


def test_logout_clears_whole_session(logged_in_client):
    logged_in_client.get('/logout')
    with logged_in_client.session_transaction() as sess:
        assert dict(sess) == {'_flashes': [('info', 'You have been logged out successfully.')]}


def test_install_redirect_uses_configured_app_name(client):
    response = client.get('/github/install')
    assert response.status_code == 302
    assert response.headers['Location'] == 'https://github.com/apps/repomaster-test/installations/new'


# --- Files -------------------------------------------------------------------

def test_update_and_delete_file_have_distinct_urls(app):
    with app.test_request_context():
        update_url = url_for('main.update_existing_file', owner='o', repo='r', path='a/b.txt')
        delete_url = url_for('main.delete_existing_file', owner='o', repo='r', path='a/b.txt')
    assert update_url != delete_url


def test_delete_file_route_calls_delete_file(logged_in_client, monkeypatch):
    calls = []
    monkeypatch.setattr(content_routes, 'delete_file', lambda *args: calls.append(args) or {'commit': {}})

    response = logged_in_client.post('/github/repos/alice/repo/files/delete/docs/a.txt',
                                     data={'sha': 'abc', 'branch': 'dev'})

    assert calls == [('alice', 'repo', 'docs/a.txt', 'abc', 'Delete file', 'dev')]
    assert response.status_code == 302
    assert 'path=docs' in response.headers['Location']
    assert 'branch=dev' in response.headers['Location']


def test_update_file_route_calls_update_file(logged_in_client, monkeypatch):
    calls = []
    monkeypatch.setattr(content_routes, 'update_file', lambda *args: calls.append(args) or {'commit': {}})

    response = logged_in_client.post('/github/repos/alice/repo/files/update/a.txt',
                                     data={'sha': 'abc', 'content': 'new', 'message': 'msg', 'branch': ''})

    assert calls == [('alice', 'repo', 'a.txt', 'new', 'abc', 'msg', '')]
    assert response.status_code == 302


def test_create_file_sends_base64_content_and_branch(app, fake_token, monkeypatch):
    sent = {}

    def fake_put(url, headers, json, timeout):
        sent.update(url=url, json=json)
        return FakeResponse(201, {'content': {}})

    monkeypatch.setattr(repo_controller.requests, 'put', fake_put)
    with app.test_request_context():
        repo_controller.create_file('alice', 'repo', '/notes/héllo.txt', 'héllo', 'add', 'dev')

    assert sent['url'].endswith('/repos/alice/repo/contents/notes/héllo.txt')
    assert base64.b64decode(sent['json']['content']).decode('utf-8') == 'héllo'
    assert sent['json']['branch'] == 'dev'


def test_update_file_failure_returns_none_instead_of_crashing(app, fake_token, monkeypatch):
    def failing_put(*args, **kwargs):
        raise requests.ConnectionError("network down")  # no response object

    monkeypatch.setattr(repo_controller.requests, 'put', failing_put)
    with app.test_request_context():
        assert repo_controller.update_file('alice', 'repo', 'a.txt', 'x', 'sha', 'msg') is None


def test_contents_page_handles_single_file_and_string_branches(logged_in_client, monkeypatch):
    monkeypatch.setattr(content_routes, 'get_repository_contents',
                        lambda *a: {'name': 'a.txt', 'path': 'a.txt', 'type': 'file', 'sha': 's', 'download_url': '#'})
    monkeypatch.setattr(content_routes, 'get_branches', lambda *a: ['main', 'dev'])
    monkeypatch.setattr(content_routes, 'get_github_issues', lambda *a: [])
    monkeypatch.setattr(content_routes, 'get_pull_requests', lambda *a: [])

    response = logged_in_client.get('/github/repos/alice/repo/contents?path=a.txt')

    assert response.status_code == 200
    assert b'<strong>a.txt</strong>' in response.data
    assert b'branch=dev' in response.data  # branch dropdown links use the branch name


# --- Repositories ------------------------------------------------------------

def test_get_github_repositories_uses_installation_endpoint(app, monkeypatch):
    seen = {}

    def fake_get(url, headers, params, timeout):
        seen['url'] = url
        return FakeResponse(200, {'repositories': [{'name': 'private-repo', 'language': 'Python'}]})

    monkeypatch.setattr(repo_controller.requests, 'get', fake_get)
    repos = repo_controller.get_github_repositories('fake-token')

    assert seen['url'] == 'https://api.github.com/installation/repositories'
    assert repos[0]['name'] == 'private-repo'
    assert repos[0]['language_color'] == '#3572A5'


def test_repositories_page_renders_with_no_repositories(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(repo_routes, 'get_github_repositories', lambda token: [])
    assert logged_in_client.get('/github/repositories').status_code == 200


def test_delete_repository_uses_logged_in_username(app, fake_token, monkeypatch):
    deleted_urls = []
    monkeypatch.setattr(repo_controller.requests, 'delete',
                        lambda url, headers, timeout: deleted_urls.append(url) or FakeResponse(204))

    with app.test_request_context():
        session['github_username'] = 'alice'
        message = repo_controller.delete_repository(['repo-a'])

    assert deleted_urls == ['https://api.github.com/repos/alice/repo-a']
    assert 'repo-a' in message


def test_delete_repository_refuses_without_username(app, fake_token, monkeypatch):
    def must_not_delete(*args, **kwargs):
        raise AssertionError("should not call the GitHub API")

    monkeypatch.setattr(repo_controller.requests, 'delete', must_not_delete)
    with app.test_request_context():
        message = repo_controller.delete_repository(['repo-a'])
    assert 'log in again' in message


def test_delete_repo_result_message_is_displayed(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(repo_routes, 'delete_repository', lambda names: "Repositories 'repo-a' deleted successfully.")
    monkeypatch.setattr(repo_routes, 'get_github_repositories', lambda token: [])

    response = logged_in_client.post('/delete_repo', data={'repo_to_delete[]': ['repo-a']}, follow_redirects=True)

    assert b"deleted successfully" in response.data


# --- Branches ----------------------------------------------------------------

def test_get_branch_details_failure_returns_error_tuple(app, fake_token, monkeypatch):
    def failing_get(*args, **kwargs):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(repo_controller.requests, 'get', failing_get)
    with app.test_request_context():
        details, error = repo_controller.get_branch_details('alice', 'repo', 'main')
    assert details is None
    assert 'main' in error


def test_create_branch_failure_redirects_instead_of_500(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(branch_routes, 'create_branch', lambda *args: None)
    response = logged_in_client.post('/repos/alice/repo/git/refs', data={'ref': 'feature', 'sha': 'abc'})
    assert response.status_code == 302


def test_rename_failure_redirects_to_valid_branch_details_url(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(branch_routes.requests, 'post',
                        lambda *args, **kwargs: FakeResponse(422, {'message': 'Invalid name'}))

    response = logged_in_client.post('/repos/alice/repo/branches/main/rename', data={'new_name': 'bad name'})

    location = response.headers['Location']
    assert 'repo_name=repo' in location
    assert 'branch_name=main' in location
    assert 'owner=alice' in location


# --- Issues & pull requests --------------------------------------------------

def test_issue_creation_failure_returns_500(logged_in_client, monkeypatch):
    monkeypatch.setattr(issue_routes, 'create_github_issue', lambda *args: None)
    response = logged_in_client.post('/repositories/repo/issues', data={'title': 'Bug'})
    assert response.status_code == 500


def test_merge_refused_by_github_is_reported(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(pull_request_routes, 'apply_pull_request_action',
                        lambda *args: (None, 'Could not merge: Pull Request is not mergeable'))
    response = logged_in_client.post('/repositories/repo/pull_requests/3', data={'action': 'merge'})
    assert response.status_code == 302
    with logged_in_client.session_transaction() as sess:
        assert sess['_flashes'] == [('error', 'Could not merge: Pull Request is not mergeable')]


def test_invalid_pr_number_returns_400(logged_in_client, fake_token):
    response = logged_in_client.get('/repositories/repo/pull_requests?pr_number=abc')
    assert response.status_code == 400
