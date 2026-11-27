"""Tests for the cleanup dashboard (issue #36) and bulk delete. GitHub is never contacted."""
from datetime import datetime, timezone
import pytest

from app.controllers import bulk_controller, cleanup_controller, repo_controller
from app.controllers.cleanup_controller import (
    analyze_branches, analyze_repositories, find_unmodified_forks, parse_github_date, parse_months,
)
from app.routes import bulk_routes, cleanup_routes

NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)


def repo(full_name, **fields):
    return {'full_name': full_name, 'private': False, 'archived': False, 'fork': False,
            'size': 10, 'pushed_at': '2026-10-20T00:00:00Z', 'description': '', **fields}


def commit_on(date):
    return {'commit': {'committer': {'date': date}}}


# --- Helpers -----------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    (None, 6), ('', 6), ('abc', 6), ('12', 12), ('0', 1), ('-3', 1), ('999', 60),
])
def test_parse_months(value, expected):
    assert parse_months(value) == expected


def test_parse_github_date():
    assert parse_github_date('2024-01-31T12:00:00Z') == datetime(2024, 1, 31, 12, tzinfo=timezone.utc)
    assert parse_github_date(None) is None
    assert parse_github_date('not a date') is None


# --- Repository analysis ------------------------------------------------------

def test_analyze_repositories_flags_candidates():
    repos = [
        repo('alice/fresh'),
        repo('alice/old', pushed_at='2025-01-01T00:00:00Z'),
        repo('alice/older', pushed_at='2024-01-01T00:00:00Z'),
        repo('alice/empty', size=0),
        repo('alice/a-fork', fork=True),
        repo('alice/archived', archived=True, size=0, pushed_at='2020-01-01T00:00:00Z'),
        repo('alice/never-pushed', pushed_at=None),
    ]

    result = analyze_repositories(repos, months=6, now=NOW)

    assert [r['full_name'] for r in result['inactive']] == ['alice/older', 'alice/old']
    assert [r['full_name'] for r in result['empty']] == ['alice/empty']
    assert [r['full_name'] for r in result['forks']] == ['alice/a-fork']
    assert result['archived_count'] == 1


def test_inactivity_threshold_is_configurable():
    repos = [repo('alice/two-months', pushed_at='2026-09-01T00:00:00Z')]
    assert analyze_repositories(repos, months=1, now=NOW)['inactive']
    assert not analyze_repositories(repos, months=6, now=NOW)['inactive']


# --- Forks -------------------------------------------------------------------

@pytest.fixture
def fake_api(monkeypatch):
    """Patch the GitHub helpers used by cleanup_controller with dict-driven fakes."""
    api = {'repos': {}, 'branches': {}, 'compare': {}, 'compare_calls': []}

    def get_repository(owner, name, token):
        data = api['repos'].get(f'{owner}/{name}')
        return (data, None) if data else (None, 'Not Found')

    def list_branches(owner, name, token):
        return api['branches'].get(f'{owner}/{name}', []), None

    def compare_refs(owner, name, base, head, token):
        api['compare_calls'].append((f'{owner}/{name}', base, head))
        result = api['compare'].get((f'{owner}/{name}', base, head))
        if isinstance(result, str):
            return None, result
        return result, None

    monkeypatch.setattr(cleanup_controller, 'get_repository', get_repository)
    monkeypatch.setattr(cleanup_controller, 'list_branches', list_branches)
    monkeypatch.setattr(cleanup_controller, 'compare_refs', compare_refs)
    return api


def test_find_unmodified_forks(fake_api):
    fake_api['repos'] = {
        'alice/same': {'default_branch': 'main', 'parent': {'full_name': 'up/same', 'default_branch': 'main'}},
        'alice/changed': {'default_branch': 'dev', 'parent': {'full_name': 'up/changed', 'default_branch': 'trunk'}},
    }
    fake_api['compare'] = {
        ('up/same', 'main', 'alice:main'): {'ahead_by': 0},
        ('up/changed', 'trunk', 'alice:dev'): {'ahead_by': 3},
    }

    unmodified, unchecked = find_unmodified_forks(
        [repo('alice/same', fork=True), repo('alice/changed', fork=True), repo('alice/gone', fork=True)], 'tok')

    assert [(f['full_name'], f['parent']) for f in unmodified] == [('alice/same', 'up/same')]
    assert [(u['repo']['full_name'], u['reason']) for u in unchecked] == [('alice/gone', 'Not Found')]


# --- Branches ----------------------------------------------------------------

def test_analyze_branches_classifies_merged_stale_and_active(fake_api):
    r = 'alice/app'
    fake_api['repos'][r] = {'default_branch': 'main'}
    fake_api['branches'][r] = [
        {'name': 'main', 'protected': True},
        {'name': 'feature/done', 'protected': False},
        {'name': 'release', 'protected': True},
        {'name': 'old-idea', 'protected': False},
        {'name': 'wip', 'protected': False},
        {'name': 'broken', 'protected': False},
    ]
    fake_api['compare'] = {
        (r, 'main', 'feature/done'): {'ahead_by': 0, 'commits': []},
        (r, 'main', 'release'): {'ahead_by': 0, 'commits': []},
        (r, 'main', 'old-idea'): {'ahead_by': 2, 'commits': [commit_on('2025-01-01T00:00:00Z'),
                                                             commit_on('2025-02-01T00:00:00Z')]},
        (r, 'main', 'wip'): {'ahead_by': 1, 'commits': [commit_on('2026-10-30T00:00:00Z')]},
        (r, 'main', 'broken'): 'Not Found',
    }

    result, error = analyze_branches('alice', 'app', 'tok', months=6, now=NOW)

    assert error is None
    assert result['default_branch'] == 'main'
    assert [(b['name'], b['protected']) for b in result['merged']] == [('feature/done', False), ('release', True)]
    assert [b['name'] for b in result['stale']] == ['old-idea']
    assert result['stale'][0]['last_commit_date'] == datetime(2025, 2, 1, tzinfo=timezone.utc)
    assert result['active_count'] == 1
    assert result['unchecked'] == [{'name': 'broken', 'reason': 'Not Found'}]
    assert all(call[2] != 'main' for call in fake_api['compare_calls'])  # default branch not compared


def test_analyze_branches_reports_repository_error(fake_api):
    assert analyze_branches('alice', 'missing', 'tok', months=6, now=NOW) == (None, 'Not Found')


def test_branch_names_are_url_encoded(monkeypatch):
    seen = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        seen['url'] = url

        class Response:
            status_code = 204

            def raise_for_status(self):
                pass

        return Response()

    monkeypatch.setattr(repo_controller.requests, 'request', fake_request)
    assert repo_controller.delete_branch_ref('alice', 'app', 'feature/a#b', 'tok') == (True, None)
    assert seen['url'] == 'https://api.github.com/repos/alice/app/git/refs/heads/feature/a%23b'


# --- Routes ------------------------------------------------------------------

@pytest.fixture
def fake_token(monkeypatch):
    for module in (cleanup_routes, bulk_routes):
        monkeypatch.setattr(module, 'get_installation_access_token', lambda: 'tok')


@pytest.mark.parametrize('method, url', [
    ('get', '/repositories/cleanup'),
    ('get', '/repositories/cleanup/branches?repo=alice/app'),
    ('post', '/repositories/cleanup/branches/delete'),
])
def test_cleanup_routes_require_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


def test_dashboard_renders_sections_with_bulk_buttons(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(cleanup_routes, 'get_github_repositories', lambda token: [
        repo('alice/old', pushed_at='2020-01-01T00:00:00Z'),
        repo('alice/empty', size=0),
        repo('alice/fork', fork=True),
    ])
    monkeypatch.setattr(cleanup_routes, 'find_unmodified_forks',
                        lambda forks, token: ([{**forks[0], 'parent': 'up/fork'}], []))

    response = logged_in_client.get('/repositories/cleanup?months=12')
    html = response.data.decode()

    assert response.status_code == 200
    assert 'value="alice/old"' in html and '2020-01-01' in html
    assert 'value="alice/empty"' in html
    assert '<code>up/fork</code>' in html
    assert 'action="/repositories/bulk/confirm"' in html
    assert 'name="action" value="archive"' in html and 'name="action" value="delete"' in html
    assert '<option value="12" selected>' in html


def test_branch_review_page(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(cleanup_routes, 'analyze_branches', lambda owner, name, token, months: ({
        'default_branch': 'main', 'active_count': 2, 'unchecked': [], 'truncated': False,
        'merged': [{'name': 'done', 'protected': False, 'ahead_by': 0, 'last_commit_date': None}],
        'stale': [{'name': 'locked', 'protected': True, 'ahead_by': 4,
                   'last_commit_date': datetime(2025, 1, 1, tzinfo=timezone.utc)}],
    }, None))

    html = logged_in_client.get('/repositories/cleanup/branches?repo=alice/app').data.decode()

    assert 'value="done"' in html
    assert 'value="locked"' in html and 'disabled' in html
    assert '2025-01-01' in html


def test_branch_review_rejects_invalid_repo(logged_in_client):
    response = logged_in_client.get('/repositories/cleanup/branches?repo=../../etc')
    assert response.status_code == 302


@pytest.fixture
def branch_api(monkeypatch):
    deleted = []
    monkeypatch.setattr(cleanup_routes, 'get_repository', lambda o, n, t: ({'default_branch': 'main'}, None))
    monkeypatch.setattr(cleanup_routes, 'list_branches', lambda o, n, t: ([
        {'name': 'main', 'protected': True},
        {'name': 'done', 'protected': False},
        {'name': 'locked', 'protected': True},
        {'name': 'fails', 'protected': False},
    ], None))

    def delete_branch_ref(owner, name, branch, token):
        if branch == 'fails':
            return False, 'Reference does not exist'
        deleted.append(branch)
        return True, None

    monkeypatch.setattr(cleanup_routes, 'delete_branch_ref', delete_branch_ref)
    return deleted


def test_branch_delete_never_deletes_default_or_protected(logged_in_client, fake_token, branch_api):
    response = logged_in_client.post('/repositories/cleanup/branches/delete', data={
        'repo': 'alice/app', 'months': '6', 'branches': ['done', 'main', 'locked', 'fails', 'ghost'],
    })

    assert branch_api == ['done']
    assert response.status_code == 302
    assert 'repo=alice/app' in response.headers['Location']
    with logged_in_client.session_transaction() as sess:
        messages = dict((m, c) for c, m in sess['_flashes'])
    assert 'Deleted 1 branch(es): done' in messages
    not_deleted = next(m for m in messages if m.startswith('Not deleted'))
    for reason in ('main (default branch)', 'locked (protected)', 'fails (Reference does not exist)', 'ghost (not found)'):
        assert reason in not_deleted


def test_branch_delete_requires_a_selection(logged_in_client, fake_token, branch_api):
    logged_in_client.post('/repositories/cleanup/branches/delete', data={'repo': 'alice/app'})
    assert branch_api == []


# --- Bulk delete (used by the dashboard's Delete button) -----------------------

def test_bulk_delete_schedules_deletion(monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_controller, 'schedule_deletion',
                        lambda owner, name, token: calls.append(f'{owner}/{name}') or (True, 'Scheduled'))
    bulk_request, _ = bulk_controller.validate_bulk_request('delete', ['alice/one'])

    assert bulk_controller.apply_bulk_action('tok', bulk_request) == [
        {'repo': 'alice/one', 'ok': True, 'message': 'Scheduled'}]
    assert calls == ['alice/one']


def test_bulk_delete_confirm_page_asks_for_typed_confirmation(logged_in_client):
    html = logged_in_client.post('/repositories/bulk/confirm', data={
        'action': 'delete', 'repos': ['alice/one']}).data.decode()
    assert 'permanently deleted after 7 days' in html
    assert 'name="confirmation"' in html
    assert 'Delete 1 repository' in html


def test_bulk_delete_confirm_without_grace_period(app, logged_in_client):
    app.config['SOFT_DELETE_DAYS'] = 0
    html = logged_in_client.post('/repositories/bulk/confirm', data={
        'action': 'delete', 'repos': ['alice/one']}).data.decode()
    assert 'This cannot be undone.' in html


@pytest.mark.parametrize('confirmation', [None, '', 'yes', 'DELETE IT'])
def test_bulk_delete_without_typed_confirmation_is_refused(logged_in_client, fake_token, monkeypatch, confirmation):
    monkeypatch.setattr(bulk_routes, 'apply_bulk_action', lambda *a: pytest.fail("must not delete"))
    data = {'action': 'delete', 'repos': ['alice/one']}
    if confirmation is not None:
        data['confirmation'] = confirmation

    response = logged_in_client.post('/repositories/bulk/apply', data=data)

    assert response.status_code == 400
    assert b"Type &#39;delete&#39; to confirm" in response.data


def test_bulk_delete_with_typed_confirmation_runs(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(bulk_routes, 'apply_bulk_action',
                        lambda token, req: [{'repo': 'alice/one', 'ok': True, 'message': 'Deleted'}])
    response = logged_in_client.post('/repositories/bulk/apply', data={
        'action': 'delete', 'repos': ['alice/one'], 'confirmation': ' Delete '})
    assert response.status_code == 200
    assert b'1 of 1 repository updated.' in response.data
