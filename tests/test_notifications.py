"""Tests for the webhook receiver and in-app notifications (issue #46). GitHub is never contacted."""
import hashlib
import hmac
import json
import pytest

from app.controllers import notifications_controller
from app.controllers.notifications_controller import (
    add_notification, build_notification, list_notifications, safe_link, unread_count, verify_signature,
)
from app.db import get_db

SECRET = 'test-webhook-secret'
REPOSITORY = {'full_name': 'alice/app', 'name': 'app'}


def sign(body, secret=SECRET):
    return 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def deliver(client, event, payload, delivery='d-1', secret=SECRET, signature=None):
    body = json.dumps(payload).encode()
    headers = {'X-GitHub-Event': event, 'X-GitHub-Delivery': delivery,
               'X-Hub-Signature-256': signature if signature is not None else sign(body, secret),
               'Content-Type': 'application/json'}
    return client.post('/github/webhook', data=body, headers=headers)


def payload(**fields):
    data = {'installation': {'id': 1}, 'repository': REPOSITORY, 'sender': {'login': 'bob'}}
    data.update(fields)
    return data


def pr_event(action, **pr_fields):
    return payload(action=action, pull_request={'number': 12, 'title': 'Add <login>', **pr_fields})


def stored(app):
    with app.app_context():
        return list_notifications(1)


# --- Signature ---------------------------------------------------------------

def test_verify_signature():
    body = b'{"a": 1}'
    assert verify_signature(SECRET, body, sign(body))
    assert not verify_signature(SECRET, body, sign(body, 'other-secret'))
    assert not verify_signature(SECRET, body + b' ', sign(body))
    assert not verify_signature(SECRET, body, None)
    assert not verify_signature(SECRET, body, 'sha1=' + 'a' * 40)
    assert not verify_signature('', body, sign(body, ''))


def test_webhook_rejects_bad_signatures(client, app):
    assert deliver(client, 'issues', payload(action='opened'), signature='sha256=' + '0' * 64).status_code == 401
    assert deliver(client, 'issues', payload(action='opened'), signature='').status_code == 401
    assert deliver(client, 'issues', payload(action='opened'), secret='guess').status_code == 401
    assert stored(app) == []


def test_webhook_refused_without_configured_secret(client, app):
    app.config['GITHUB_WEBHOOK_SECRET'] = None
    assert deliver(client, 'ping', {}).status_code == 503


def test_webhook_rejects_invalid_json(client):
    body = b'not json'
    response = client.post('/github/webhook', data=body,
                           headers={'X-GitHub-Event': 'push', 'X-Hub-Signature-256': sign(body)})
    assert response.status_code == 400


def test_ping(client):
    response = deliver(client, 'ping', {'zen': 'Keep it logically awesome.'})
    assert response.status_code == 200 and response.json == {'result': 'pong'}


# --- Events ------------------------------------------------------------------

@pytest.mark.parametrize('event, body, title, level', [
    ('pull_request', pr_event('opened'), 'bob opened PR #12: Add <login>', 'info'),
    ('pull_request', pr_event('closed', merged=True), 'bob merged PR #12: Add <login>', 'success'),
    ('pull_request', pr_event('closed', merged=False), 'bob closed PR #12: Add <login>', 'info'),
    ('pull_request', {**pr_event('review_requested'), 'requested_reviewer': {'login': 'carol'}},
     'PR #12 needs review from carol: Add <login>', 'warning'),
    ('pull_request', {**pr_event('review_requested'), 'requested_team': {'name': 'core'}},
     'PR #12 needs review from core: Add <login>', 'warning'),
    ('issues', payload(action='opened', issue={'number': 3, 'title': 'Crash'}), 'bob opened issue #3: Crash', 'info'),
    ('issues', payload(action='assigned', issue={'number': 3, 'title': 'Crash'}, assignee={'login': 'dave'}),
     'Issue #3 was assigned to dave: Crash', 'info'),
    ('push', payload(ref='refs/heads/main', commits=[{}, {}], pusher={'name': 'bob'},
                     compare='https://github.com/alice/app/compare/a...b'), 'bob pushed 2 commits to main', 'info'),
    ('workflow_run', payload(action='completed', workflow_run={'id': 9, 'name': 'CI', 'run_number': 42,
                                                               'head_branch': 'main', 'conclusion': 'failure'}),
     'CI failed on main: CI #42', 'danger'),
    ('check_run', payload(action='completed', check_run={'name': 'lint', 'conclusion': 'failure', 'app': {'slug': 'circleci'},
                                                         'check_suite': {'head_branch': 'dev'},
                                                         'html_url': 'https://github.com/alice/app/runs/1'}),
     'Check lint failed on dev', 'danger'),
    ('installation', {'action': 'created', 'installation': {'id': 1, 'account': {'login': 'alice'}}},
     'RepoMaster was installed on alice', 'success'),
])
def test_events_become_notifications(app, event, body, title, level):
    with app.test_request_context():
        notification = build_notification(event, body)
    assert notification['title'] == title and notification['level'] == level


def test_links_point_into_repomaster(app):
    with app.test_request_context():
        assert build_notification('pull_request', pr_event('opened'))['link'] == '/repositories/app/pull_requests?pr_number=12'
        assert build_notification('issues', payload(action='opened', issue={'number': 3, 'title': 'x'}))['link'] == \
            '/repositories/app/issues/3'
        run = payload(action='completed', workflow_run={'id': 9, 'name': 'CI', 'run_number': 1,
                                                        'head_branch': 'main', 'conclusion': 'timed_out'})
        assert build_notification('workflow_run', run)['link'] == '/repos/alice/app/actions/runs/9'


@pytest.mark.parametrize('event, body', [
    ('pull_request', pr_event('labeled')),
    ('pull_request', pr_event('synchronize')),
    ('issues', payload(action='labeled', issue={'number': 1})),
    ('push', payload(ref='refs/heads/old', deleted=True, commits=[])),
    ('push', payload(ref='refs/tags/v1', commits=[])),
    ('workflow_run', payload(action='completed', workflow_run={'id': 1, 'conclusion': 'success'})),
    ('workflow_run', payload(action='requested', workflow_run={'id': 1, 'conclusion': None})),
    ('check_run', payload(action='completed', check_run={'name': 'test', 'conclusion': 'failure',
                                                         'app': {'slug': 'github-actions'}})),
    ('star', payload(action='created')),
])
def test_noise_is_ignored(app, event, body):
    with app.test_request_context():
        assert build_notification(event, body) is None


def test_untrusted_links_are_dropped(app):
    with app.test_request_context():
        push = payload(ref='refs/heads/main', commits=[{}], compare='https://evil.example/x')
        assert build_notification('push', push)['link'] is None


# --- Delivery and storage ----------------------------------------------------

def test_delivery_is_stored_once(client, app):
    assert deliver(client, 'pull_request', pr_event('opened')).json == {'result': 'stored'}
    assert deliver(client, 'pull_request', pr_event('opened')).json == {'result': 'duplicate'}  # GitHub redelivery
    items = stored(app)
    assert len(items) == 1
    assert items[0]['title'] == 'bob opened PR #12: Add <login>' and items[0]['repo'] == 'alice/app'
    assert items[0]['read'] == 0


def test_delivery_without_installation_is_ignored(client, app):
    assert deliver(client, 'issues', {'action': 'opened', 'issue': {'number': 1}}).json == {'result': 'ignored: no installation'}


def test_uninstall_removes_that_installations_notifications(client, app):
    deliver(client, 'pull_request', pr_event('opened'), delivery='a')
    deliver(client, 'pull_request', {**pr_event('opened'), 'installation': {'id': 2}}, delivery='b')
    deliver(client, 'installation', {'action': 'deleted', 'installation': {'id': 1}}, delivery='c')
    with app.app_context():
        assert list_notifications(1) == [] and len(list_notifications(2)) == 1


def test_only_newest_notifications_are_kept(app, monkeypatch):
    monkeypatch.setattr(notifications_controller, 'MAX_PER_INSTALLATION', 3)
    with app.app_context():
        for i in range(5):
            add_notification(1, f'd{i}', {'event': 'push', 'title': f'n{i}'})
        assert [n['title'] for n in list_notifications(1)] == ['n4', 'n3', 'n2']


def test_safe_link():
    assert safe_link('/repositories/app/issues/3') == '/repositories/app/issues/3'
    assert safe_link('https://github.com/alice/app') == 'https://github.com/alice/app'
    for bad in ('//evil.example', 'https://evil.example', 'javascript:alert(1)', '/\\evil.example', None, ''):
        assert safe_link(bad) is None, bad


# --- Pages -------------------------------------------------------------------

def seed(app, installation_id=1, **fields):
    with app.app_context():
        add_notification(installation_id, fields.pop('delivery', None),
                         {'event': 'pull_request', 'title': 'PR #12 needs <review>', 'repo': 'alice/app',
                          'link': '/repositories/app/pull_requests?pr_number=12', 'level': 'warning', **fields})


def test_notifications_page_shows_own_installation_only(logged_in_client, app):
    seed(app, delivery='a')
    seed(app, installation_id=2, delivery='b', title='Someone else')
    html = logged_in_client.get('/notifications').data.decode()
    assert 'PR #12 needs &lt;review&gt;' in html and 'Someone else' not in html
    assert 'action needed' in html and 'Mark all as read' in html


def test_opening_marks_read_and_redirects(logged_in_client, app):
    seed(app, delivery='a')
    response = logged_in_client.get('/notifications/1/open')
    assert response.status_code == 302 and response.headers['Location'] == '/repositories/app/pull_requests?pr_number=12'
    with app.app_context():
        assert unread_count(1) == 0


def test_stored_bad_link_does_not_redirect_offsite(logged_in_client, app):
    seed(app, delivery='a', link='https://evil.example/phish')
    response = logged_in_client.get('/notifications/1/open')
    assert response.headers['Location'] == '/notifications'


def test_cannot_open_another_installations_notification(logged_in_client, app):
    seed(app, installation_id=2, delivery='a')
    assert logged_in_client.get('/notifications/1/open').status_code == 404
    with app.app_context():
        assert unread_count(2) == 1


def test_mark_all_read_and_unread_json(logged_in_client, app):
    seed(app, delivery='a')
    seed(app, delivery='b')
    assert logged_in_client.get('/notifications/unread.json').json == {'unread': 2}
    logged_in_client.post('/notifications/read-all')
    assert logged_in_client.get('/notifications/unread.json').json == {'unread': 0}


def test_bell_shows_unread_count(logged_in_client, app, monkeypatch):
    from app.routes import inbox_routes
    seed(app, delivery='a')
    monkeypatch.setattr(inbox_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(inbox_routes, 'get_github_repositories', lambda token: [])
    monkeypatch.setattr(inbox_routes, 'search_issues', lambda *a, **k: ({'total_count': 0, 'items': []}, None))
    html = logged_in_client.get('/inbox').data.decode()
    assert 'id="notificationBell"' in html and '1<span class="visually-hidden"> unread</span>' in html
    assert 'Notifications (1)' in logged_in_client.get('/').data.decode()


def test_home_page_without_login_does_not_touch_notifications(client):
    assert b'Notifications' not in client.get('/').data


@pytest.mark.parametrize('method, url', [('get', '/notifications'), ('post', '/notifications/read-all'),
                                         ('get', '/notifications/1/open'), ('get', '/notifications/unread.json')])
def test_notification_pages_require_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


def test_database_is_created_with_schema(app):
    with app.app_context():
        tables = {row[0] for row in get_db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert 'notifications' in tables
