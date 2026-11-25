"""Tests for the branch protection editor and branch comparison (issue #41). GitHub is never contacted."""
import pytest
from werkzeug.datastructures import MultiDict

from app.controllers import branch_management_controller
from app.controllers.branch_management_controller import (
    build_protection_payload, commit_rows, describe_comparison, parse_status_checks,
    protection_to_form, valid_branch, valid_names,
)
from app.routes import branch_routes

PROTECTION = '/repos/alice/app/branches/main/protection'

EXISTING = {
    'required_status_checks': {'strict': True, 'contexts': ['ci/tests'],
                               'checks': [{'context': 'ci/tests', 'app_id': 15368}]},
    'enforce_admins': {'enabled': True},
    'required_pull_request_reviews': {
        'required_approving_review_count': 2, 'dismiss_stale_reviews': True,
        'require_code_owner_reviews': False, 'require_last_push_approval': False,
        'dismissal_restrictions': {'users': [{'login': 'carol'}], 'teams': [{'slug': 'core'}], 'apps': []},
    },
    'restrictions': {'users': [{'login': 'alice'}], 'teams': [], 'apps': [{'slug': 'deploy-bot'}]},
    'required_linear_history': {'enabled': False},
    'allow_force_pushes': {'enabled': False},
    'allow_deletions': {'enabled': False},
    'required_conversation_resolution': {'enabled': True},
}


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: responses are looked up by (method, path); every call is recorded."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json'), kwargs.get('params')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(branch_management_controller, 'github_api', fake_api)
    monkeypatch.setattr(branch_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(branch_routes, 'list_branches', lambda owner, repo, token: (
        [{'name': 'main'}, {'name': 'feature/login'}, {'name': 'dev'}], None))
    monkeypatch.setattr(branch_routes, 'get_repository', lambda owner, repo, token: ({'default_branch': 'main'}, None))
    return state


def flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


# --- Names -------------------------------------------------------------------

def test_valid_names_and_branches():
    assert valid_names('alice', 'my-app.js')
    assert not valid_names('alice', '..') and not valid_names('a/b', 'x') and not valid_names('', 'x')
    assert valid_branch('feature/login') and valid_branch('release-1.0')
    for bad in ('', '../main', 'a..b', 'has space', 'x.lock', '/lead', 'trail/', 'a~1'):
        assert not valid_branch(bad), bad


# --- Protection form ---------------------------------------------------------

def test_unprotected_branch_form_is_all_off():
    settings = protection_to_form(None)
    assert settings['protected'] is False
    assert not settings['require_pull_request'] and not settings['require_status_checks']
    assert settings['required_approvals'] == 1


def test_existing_protection_fills_form():
    settings = protection_to_form(EXISTING)
    assert settings['protected'] and settings['require_pull_request']
    assert settings['required_approvals'] == 2
    assert settings['dismiss_stale_reviews'] and not settings['require_code_owner_reviews']
    assert settings['require_status_checks'] and settings['strict_status_checks']
    assert settings['status_checks'] == 'ci/tests'
    assert settings['enforce_admins'] and settings['required_conversation_resolution']
    assert not settings['allow_force_pushes'] and settings['has_restrictions']


def test_payload_from_form():
    form = MultiDict({'require_pull_request': 'on', 'required_approvals': '1', 'require_status_checks': 'on',
                      'status_checks': ' tests \n\nlint\ntests\n', 'allow_deletions': 'on'})
    payload, error = build_protection_payload(form)
    assert error is None
    assert payload == {
        'required_status_checks': {'strict': False, 'checks': [{'context': 'tests'}, {'context': 'lint'}]},
        'enforce_admins': False,
        'required_pull_request_reviews': {'required_approving_review_count': 1, 'dismiss_stale_reviews': False,
                                          'require_code_owner_reviews': False, 'require_last_push_approval': False},
        'restrictions': None,
        'required_linear_history': False,
        'required_conversation_resolution': False,
        'allow_force_pushes': False,
        'allow_deletions': True,
    }


def test_unchecked_sections_are_turned_off():
    payload, _ = build_protection_payload(MultiDict({'required_approvals': '3', 'status_checks': 'tests'}))
    assert payload['required_pull_request_reviews'] is None
    assert payload['required_status_checks'] is None


def test_settings_the_editor_does_not_show_are_kept():
    form = MultiDict({'require_pull_request': 'on', 'required_approvals': '2',
                      'require_status_checks': 'on', 'status_checks': 'ci/tests\nlint'})
    payload, _ = build_protection_payload(form, EXISTING)
    assert payload['restrictions'] == {'users': ['alice'], 'teams': [], 'apps': ['deploy-bot']}
    assert payload['required_pull_request_reviews']['dismissal_restrictions'] == \
        {'users': ['carol'], 'teams': ['core'], 'apps': []}
    # The existing check keeps its required app; a new check accepts any app
    assert payload['required_status_checks']['checks'] == [{'context': 'ci/tests', 'app_id': 15368}, {'context': 'lint'}]


@pytest.mark.parametrize('approvals', ['7', '-1', 'two'])
def test_invalid_approval_counts(approvals):
    payload, error = build_protection_payload(MultiDict({'require_pull_request': 'on', 'required_approvals': approvals}))
    assert payload is None and 'approvals' in error


def test_status_check_names_are_validated():
    assert parse_status_checks('a\nb\na') == (['a', 'b'], None)
    assert parse_status_checks('x' * 256)[1].endswith("isn't a valid status check name.")
    assert parse_status_checks('bad\x07name')[0] is None
    assert 'At most 50' in parse_status_checks('\n'.join(f'c{i}' for i in range(51)))[1]


# --- Protection routes -------------------------------------------------------

def test_protection_page_for_unprotected_branch(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (None, 'Branch not protected')
    html = logged_in_client.get('/repos/alice/app/branch-protection?branch=main').data.decode()
    assert 'not protected' in html and 'Protect branch' in html and 'Remove protection' not in html


def test_protection_page_shows_current_rules(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (EXISTING, None)
    html = logged_in_client.get('/repos/alice/app/branch-protection?branch=main').data.decode()
    assert '<option value="2" selected>2</option>' in html
    assert 'ci/tests</textarea>' in html
    assert 'Remove protection' in html and 'restricts who can push' in html


def test_branch_with_slash_is_encoded(logged_in_client, github):
    logged_in_client.get('/repos/alice/app/branch-protection?branch=feature/login')
    assert github['calls'][0][1] == '/repos/alice/app/branches/feature%2Flogin/protection'


@pytest.mark.parametrize('url', [
    '/repos/alice/app/branch-protection?branch=../../x',
    '/repos/alice/app/branch-protection',
    '/repos/alice/..%2F..%2Fx/branch-protection?branch=main',
])
def test_invalid_names_are_rejected(logged_in_client, github, url):
    assert logged_in_client.get(url).status_code in (400, 404)
    assert github['calls'] == []


def test_load_error_is_shown(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (None, 'Resource not accessible by integration')
    response = logged_in_client.get('/repos/alice/app/branch-protection?branch=main')
    assert response.status_code == 502
    assert b'Resource not accessible by integration' in response.data


def test_saving_protection(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (None, 'Branch not protected')
    github['responses'][('PUT', PROTECTION)] = ({}, None)
    response = logged_in_client.post('/repos/alice/app/branch-protection', data={
        'branch': 'main', 'action': 'save', 'require_pull_request': 'on', 'required_approvals': '1'})
    assert response.headers['Location'].endswith('/repos/alice/app/branch-protection?branch=main')
    method, path, payload, _ = github['calls'][-1]
    assert (method, path) == ('PUT', PROTECTION)
    assert payload['required_pull_request_reviews']['required_approving_review_count'] == 1
    assert flashes(logged_in_client) == [('success', 'Protection rules for main saved.')]


def test_save_error_from_github_is_flashed(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (None, 'Branch not protected')
    github['responses'][('PUT', PROTECTION)] = (None, 'Upgrade to GitHub Pro or make this repository public')
    logged_in_client.post('/repos/alice/app/branch-protection', data={'branch': 'main', 'action': 'save'})
    assert flashes(logged_in_client) == [
        ('error', "Couldn't save protection rules: Upgrade to GitHub Pro or make this repository public")]


def test_invalid_form_is_not_sent(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (None, 'Branch not protected')
    logged_in_client.post('/repos/alice/app/branch-protection', data={
        'branch': 'main', 'action': 'save', 'require_pull_request': 'on', 'required_approvals': '9'})
    assert [call[0] for call in github['calls']] == ['GET']


def test_removing_protection(logged_in_client, github):
    github['responses'][('GET', PROTECTION)] = (EXISTING, None)
    github['responses'][('DELETE', PROTECTION)] = (None, None)
    logged_in_client.post('/repos/alice/app/branch-protection', data={'branch': 'main', 'action': 'remove'})
    assert github['calls'][-1][:2] == ('DELETE', PROTECTION)
    assert flashes(logged_in_client) == [('success', 'Protection removed from main.')]


# --- Comparison --------------------------------------------------------------

COMPARE = '/repos/alice/app/compare/main...feature/login'
COMPARISON = {
    'status': 'diverged', 'ahead_by': 2, 'behind_by': 1, 'total_commits': 2,
    'html_url': 'https://github.com/alice/app/compare/main...feature/login', 'files': [{'filename': 'a.py'}],
    'commits': [
        {'sha': 'abcdef1234', 'html_url': 'https://github.com/c/1', 'author': {'login': 'bob'},
         'commit': {'message': 'Add login\n\nLong body', 'author': {'name': 'Bob', 'date': '2026-11-20T10:00:00Z'}}},
        {'sha': '9876543210', 'author': None,
         'commit': {'message': 'Fix <typo>', 'author': {'name': 'Ghost', 'date': None}}},
    ],
}


@pytest.mark.parametrize('status, ahead, behind, text', [
    ('identical', 0, 0, 'feature and main are identical.'),
    ('ahead', 1, 0, 'feature is 1 commit ahead of main.'),
    ('behind', 0, 3, 'feature is 3 commits behind main.'),
    ('diverged', 2, 1, 'feature and main have diverged: feature is 2 commits ahead and 1 behind.'),
])
def test_describe_comparison(status, ahead, behind, text):
    assert describe_comparison({'status': status, 'ahead_by': ahead, 'behind_by': behind}, 'main', 'feature') == text


def test_commit_rows():
    rows = commit_rows(COMPARISON['commits'])
    assert rows[0] == {'sha': 'abcdef1', 'html_url': 'https://github.com/c/1', 'message': 'Add login',
                       'author': 'bob', 'date': '2026-11-20T10:00:00Z'}
    assert rows[1]['author'] == 'Ghost'


def test_compare_page_defaults_base_to_default_branch(logged_in_client, github):
    html = logged_in_client.get('/repos/alice/app/compare').data.decode()
    assert '<option value="main" selected>main</option>' in html
    assert github['calls'] == []  # nothing to compare until a head branch is chosen


def test_compare_shows_counts_commits_and_open_pr_link(logged_in_client, github):
    github['responses'][('GET', COMPARE)] = (COMPARISON, None)
    github['responses'][('GET', '/repos/alice/app/pulls')] = ([], None)
    html = logged_in_client.get('/repos/alice/app/compare?base=main&head=feature/login').data.decode()

    assert 'feature/login and main have diverged' in html
    assert '2 ahead' in html and '1 behind' in html
    assert 'Add login' in html and 'Long body' not in html
    assert 'Fix &lt;typo&gt;' in html
    assert '/repositories/app/pull_requests?create=1&amp;base=main&amp;head=feature/login' in html
    assert github['calls'][-1][3] == {'state': 'open', 'base': 'main', 'head': 'alice:feature/login', 'per_page': 1}


def test_compare_links_to_existing_pull_request(logged_in_client, github):
    github['responses'][('GET', COMPARE)] = (COMPARISON, None)
    github['responses'][('GET', '/repos/alice/app/pulls')] = ([{'number': 9, 'html_url': 'x'}], None)
    html = logged_in_client.get('/repos/alice/app/compare?base=main&head=feature/login').data.decode()
    assert 'View open PR #9' in html and 'Open pull request' not in html


def test_compare_identical_offers_no_pull_request(logged_in_client, github):
    github['responses'][('GET', '/repos/alice/app/compare/main...dev')] = (
        {'status': 'identical', 'ahead_by': 0, 'behind_by': 0, 'commits': [], 'files': []}, None)
    html = logged_in_client.get('/repos/alice/app/compare?base=main&head=dev').data.decode()
    assert 'dev and main are identical.' in html and 'Open pull request' not in html
    assert not any('/pulls' in call[1] for call in github['calls'])


@pytest.mark.parametrize('query, message', [
    ('base=main&head=main', 'Choose two different branches.'),
    ('base=main&head=a..b', 'Choose two valid branch names.'),
])
def test_compare_rejects_bad_choices(logged_in_client, github, query, message):
    html = logged_in_client.get(f'/repos/alice/app/compare?{query}').data.decode()
    assert message in html
    assert github['calls'] == []


def test_compare_error_is_shown(logged_in_client, github):
    html = logged_in_client.get('/repos/alice/app/compare?base=main&head=dev').data.decode()
    assert "Couldn&#39;t compare main and dev: Not Found" in html


def test_new_pull_request_form_is_prefilled(logged_in_client, monkeypatch):
    from app.routes import pull_request_routes
    monkeypatch.setattr(pull_request_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(pull_request_routes, 'get_branches', lambda owner, repo_name: ['main', 'dev'])
    html = logged_in_client.get('/repositories/app/pull_requests?create=1&base=main&head=dev').data.decode()
    assert '<option value="main" selected>main</option>' in html
    assert '<option value="dev" selected>dev</option>' in html


@pytest.mark.parametrize('url', ['/repos/alice/app/compare', '/repos/alice/app/branch-protection?branch=main'])
def test_pages_require_login(client, url):
    assert client.get(url).status_code == 403
