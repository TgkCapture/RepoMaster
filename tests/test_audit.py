"""Tests for the audit log and soft delete (issue #51). GitHub is never contacted."""
from datetime import datetime, timedelta, timezone
import pytest

from app.controllers import soft_delete_controller
from app.controllers.audit_controller import (
    SYSTEM_ACTOR, list_audit_entries, parse_audit_filters, record_audit,
)
from app.controllers.soft_delete_controller import (
    cancel_deletion, list_deletions, run_due_deletions, schedule_deletion,
)
from app.db import get_db

NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
REPO = '/repos/alice/app'


@pytest.fixture
def github(monkeypatch):
    """A fake github_api for the soft delete controller: (method, path) -> (data, error)."""
    state = {'calls': [], 'responses': {('GET', REPO): ({'archived': False}, None),
                                        ('PATCH', REPO): ({}, None), ('DELETE', REPO): (None, None)}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(soft_delete_controller, 'github_api', fake_api)
    return state


@pytest.fixture
def ctx(app):
    """A request context signed in as alice on installation 1."""
    with app.test_request_context():
        from flask import session
        session.update(installation_id=1, github_user_login='alice', github_username='alice')
        yield


def entries(**filters):
    return list_audit_entries(1, {'page': 1, **filters})[0]


def rows():
    return [dict(r) for r in get_db().execute('SELECT * FROM scheduled_deletions ORDER BY id')]


# --- Audit log ---------------------------------------------------------------

def test_record_uses_session_and_lists_newest_first(ctx):
    assert record_audit('branch.delete', 'alice/app', True, 'Deleted', target='old')
    assert record_audit('file.delete', 'alice/site', False, 'Not Found', target='a.txt')
    found = entries()
    assert [(e['action'], e['ok'], e['actor']) for e in found] == [('file.delete', 0, 'alice'), ('branch.delete', 1, 'alice')]
    assert found[1]['label'] == 'Branch deleted' and found[1]['target'] == 'old' and found[1]['ago'] == 'just now'


def test_unknown_action_is_a_programming_error(ctx):
    with pytest.raises(ValueError):
        record_audit('repository.explode', 'alice/app', True)


def test_record_without_actor_is_not_stored(app):
    with app.app_context():
        assert record_audit('branch.delete', 'alice/app', True) is False
        assert list_audit_entries(1, {'page': 1})[1] == 0


def test_record_survives_database_errors(ctx, monkeypatch):
    from app.controllers import audit_controller

    def broken():
        raise RuntimeError('disk full')
    monkeypatch.setattr(audit_controller, 'get_db', broken)
    assert record_audit('branch.delete', 'alice/app', True) is False


def test_filters(ctx):
    record_audit('branch.delete', 'alice/app', True)
    record_audit('branch.delete', 'alice/app_v2', False, 'x')
    record_audit('file.delete', 'alice/other', True)
    record_audit('file.delete', 'alice/app', True, installation_id=2, actor='bob')  # explicit values win (scheduler)
    assert len(entries(action='branch.delete')) == 2
    assert len(entries(result='failed')) == 1
    assert len(entries(repo='app_')) == 1  # "_" is literal, not a wildcard
    assert len(entries(actor='alice')) == 3
    assert list_audit_entries(2, {'page': 1})[0][0]['actor'] == 'bob'


def test_parse_filters():
    filters, warnings = parse_audit_filters({'action': 'branch.delete', 'result': 'ok', 'repo': 'app', 'page': '3'})
    assert filters == {'action': 'branch.delete', 'result': 'ok', 'repo': 'app', 'actor': '', 'page': 3}
    filters, warnings = parse_audit_filters({'action': 'drop', 'result': 'maybe', 'repo': "x' OR 1=1", 'page': 'x'})
    assert filters == {'action': '', 'result': '', 'repo': '', 'actor': '', 'page': 1} and len(warnings) == 3


def test_paging(ctx):
    for _ in range(3):
        record_audit('branch.delete', 'alice/app', True)
    assert len(list_audit_entries(1, {'page': 2}, per_page=2)[0]) == 1


# --- Soft delete -------------------------------------------------------------

def test_schedule_archives_and_records(ctx, github):
    ok, message = schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    assert ok and message == 'alice/app archived and scheduled for deletion after 2026-12-04 12:00 UTC.'
    assert ('PATCH', REPO, {'archived': True}) in github['calls']
    assert ('DELETE', REPO, None) not in github['calls']
    row = rows()[0]
    assert row['status'] == 'pending' and row['delete_after'] == '2026-12-04T12:00:00Z' and row['was_archived'] == 0
    assert row['requested_by'] == 'alice' and row['installation_id'] == 1
    assert entries()[0]['action'] == 'repository.delete_scheduled'


def test_schedule_twice_is_one_deletion(ctx, github):
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    ok, message = schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    assert ok and 'already scheduled' in message and len(rows()) == 1


def test_schedule_already_archived_repository_does_not_patch(ctx, github):
    github['responses'][('GET', REPO)] = ({'archived': True}, None)
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    assert not any(call[0] == 'PATCH' for call in github['calls']) and rows()[0]['was_archived'] == 1


def test_schedule_failures_are_recorded(ctx, github):
    github['responses'][('PATCH', REPO)] = (None, 'Must have admin rights')
    ok, message = schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    assert not ok and 'Must have admin rights' in message and rows() == []
    assert entries()[0]['ok'] == 0


def test_zero_days_deletes_immediately(ctx, github):
    ok, message = schedule_deletion('alice', 'app', 'tok', days=0)
    assert ok and message == 'alice/app deleted.' and ('DELETE', REPO, None) in github['calls'] and rows() == []
    assert entries()[0]['action'] == 'repository.deleted'


def test_undo_unarchives(ctx, github):
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    ok, message = cancel_deletion(rows()[0]['id'], 1, 'tok')
    assert ok and 'restored' in message
    assert github['calls'][-1] == ('PATCH', REPO, {'archived': False})
    assert rows()[0]['status'] == 'cancelled' and entries()[0]['action'] == 'repository.delete_cancelled'


def test_undo_keeps_previously_archived_repository_archived(ctx, github):
    github['responses'][('GET', REPO)] = ({'archived': True}, None)
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    ok, message = cancel_deletion(rows()[0]['id'], 1, 'tok')
    assert ok and 'stays archived' in message and not any(call[0] == 'PATCH' for call in github['calls'])


def test_undo_other_installation_or_twice_is_refused(ctx, github):
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    deletion_id = rows()[0]['id']
    assert cancel_deletion(deletion_id, 2, 'tok')[0] is False
    assert cancel_deletion(deletion_id, 1, 'tok')[0] is True
    assert cancel_deletion(deletion_id, 1, 'tok')[0] is False


def test_failed_unarchive_keeps_deletion_scheduled(ctx, github):
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    github['responses'][('PATCH', REPO)] = (None, 'Forbidden')
    ok, _ = cancel_deletion(rows()[0]['id'], 1, 'tok')
    assert not ok and rows()[0]['status'] == 'pending'


# --- Scheduled job -----------------------------------------------------------

def schedule_due(github):
    schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    github['responses'][('GET', REPO)] = ({'archived': True}, None)  # archived by the schedule
    github['calls'].clear()


def test_nothing_happens_before_the_grace_period_ends(ctx, github):
    schedule_due(github)
    assert run_due_deletions(lambda i: 'tok', now=NOW + timedelta(days=6)) == []
    assert github['calls'] == []


def test_due_deletion_runs(ctx, github):
    schedule_due(github)
    tokens = []
    results = run_due_deletions(lambda i: tokens.append(i) or 'tok', now=NOW + timedelta(days=7))
    assert results == [('alice/app', 'deleted', 'Deleted as requested by alice')]
    assert tokens == [1] and ('DELETE', REPO, None) in github['calls']
    assert rows()[0]['status'] == 'deleted'
    entry = entries()[0]
    assert entry['action'] == 'repository.deleted' and entry['actor'] == SYSTEM_ACTOR and entry['ok'] == 1


def test_unarchived_repository_is_kept(ctx, github):
    schedule_due(github)
    github['responses'][('GET', REPO)] = ({'archived': False}, None)
    results = run_due_deletions(lambda i: 'tok', now=NOW + timedelta(days=8))
    assert results[0][1] == 'skipped' and ('DELETE', REPO, None) not in github['calls']
    assert entries()[0]['action'] == 'repository.delete_kept'


def test_already_gone_repository_is_skipped(ctx, github):
    schedule_due(github)
    github['responses'].pop(('GET', REPO))
    assert run_due_deletions(lambda i: 'tok', now=NOW + timedelta(days=8))[0][1:] == (
        'skipped', 'Repository no longer exists')


def test_failed_delete_can_still_be_undone(ctx, github):
    schedule_due(github)
    github['responses'][('DELETE', REPO)] = (None, 'Must have admin rights')
    assert run_due_deletions(lambda i: 'tok', now=NOW + timedelta(days=8))[0][1] == 'failed'
    assert cancel_deletion(rows()[0]['id'], 1, 'tok')[0] is True


def test_missing_token_postpones(ctx, github):
    schedule_due(github)
    assert run_due_deletions(lambda i: None, now=NOW + timedelta(days=8))[0][1] == 'pending'
    assert rows()[0]['status'] == 'pending' and github['calls'] == []


def test_cli_command(app, monkeypatch):
    from app.controllers import auth_controller
    seen = {}
    monkeypatch.setattr(soft_delete_controller, 'run_due_deletions',
                        lambda get_token: seen.setdefault('get_token', get_token) and [('alice/app', 'deleted', 'ok')])
    result = app.test_cli_runner().invoke(args=['run-scheduled-deletions'])
    assert 'alice/app: deleted (ok)' in result.output and '1 scheduled deletion(s) processed.' in result.output
    assert seen['get_token'] is auth_controller.get_installation_access_token


def test_installation_token_for_background_jobs(app, monkeypatch):
    from app.controllers import auth_controller
    posted = []

    class Response:
        status_code = 201

        def json(self):
            return {'token': 'inst-token'}

    monkeypatch.setattr(auth_controller, 'get_jwt', lambda: 'jwt')
    monkeypatch.setattr(auth_controller.github_http, 'post', lambda url, headers, timeout: posted.append(url) or Response())
    with app.app_context():  # no request, no session
        assert auth_controller.get_installation_access_token(42) == 'inst-token'
    assert posted == ['https://api.github.com/app/installations/42/access_tokens']


# --- Pages -------------------------------------------------------------------

def test_deletions_page_and_undo(logged_in_client, app, github, monkeypatch):
    from app.routes import audit_routes
    monkeypatch.setattr(audit_routes, 'get_installation_access_token', lambda: 'tok')
    with app.test_request_context():
        from flask import session
        session.update(installation_id=1, github_user_login='alice')
        schedule_deletion('alice', 'app', 'tok', days=7, now=NOW)
    html = logged_in_client.get('/deletions').data.decode()
    assert 'alice/app' in html and 'will be deleted after 2026-12-04 12:00:00 UTC' in html and 'btn-sm">Undo<' in html

    response = logged_in_client.post('/deletions/1/undo', follow_redirects=True)
    assert 'Deletion of alice/app undone' in response.data.decode()
    assert 'btn-sm">Undo<' not in logged_in_client.get('/deletions').data.decode()


def test_audit_page_shows_entries_and_filters(logged_in_client, app):
    with app.test_request_context():
        from flask import session
        session.update(installation_id=1, github_user_login='alice')
        record_audit('branch.delete', 'alice/app', True, 'Deleted', target='feature/<x>')
        record_audit('secret.delete', 'alice/app', False, 'Not Found', target='TOKEN')
    html = logged_in_client.get('/audit').data.decode()
    assert 'Branch deleted' in html and 'feature/&lt;x&gt;' in html and 'Secret deleted' in html and '2 entries' in html
    html = logged_in_client.get('/audit?result=failed').data.decode()
    assert 'Secret deleted' in html and 'Branch deleted <code' not in html


@pytest.mark.parametrize('method, url', [('get', '/audit'), ('get', '/deletions'), ('post', '/deletions/1/undo')])
def test_requires_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


# --- Hooks in existing actions -----------------------------------------------

def test_bulk_archive_is_audited(ctx, monkeypatch):
    from app.controllers import bulk_controller
    monkeypatch.setattr(bulk_controller, 'update_repository', lambda owner, repo, token, fields: ({}, None))
    request, _ = bulk_controller.validate_bulk_request('archive', ['alice/app', 'alice/site'])
    bulk_controller.apply_bulk_action('tok', request)
    assert [(e['action'], e['repo']) for e in entries()] == [
        ('repository.archive', 'alice/site'), ('repository.archive', 'alice/app')]


def test_secret_value_is_never_audited(logged_in_client, app, monkeypatch):
    from app.routes import actions_routes
    monkeypatch.setattr(actions_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(actions_routes, 'set_secret', lambda *a: None)
    logged_in_client.post('/repos/alice/app/actions/secrets',
                          data={'action': 'set', 'name': 'API_KEY', 'value': 'hunter2-very-secret'})
    with app.app_context():
        stored = [dict(r) for r in get_db().execute('SELECT * FROM audit_log')]
    assert len(stored) == 1 and stored[0]['action'] == 'secret.set' and stored[0]['target'] == 'API_KEY'
    assert 'hunter2' not in repr(stored)


def test_collaborator_removal_is_audited(logged_in_client, app, monkeypatch):
    from app.routes import collaborator_routes
    monkeypatch.setattr(collaborator_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(collaborator_routes, 'apply_collaborator_action', lambda *a: ("Removed bob's access.", None))
    logged_in_client.post('/repos/alice/app/collaborators', data={'action': 'remove', 'login': 'bob'})
    with app.app_context():
        entry = dict(get_db().execute('SELECT * FROM audit_log').fetchone())
    assert (entry['action'], entry['target'], entry['actor'], entry['ok']) == ('collaborator.remove', 'bob', 'alice', 1)


def test_branch_delete_is_audited(logged_in_client, app, monkeypatch):
    from app.routes import branch_routes

    class Response:
        status_code = 204
    monkeypatch.setattr(branch_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(branch_routes.github_http, 'delete', lambda url, headers, timeout: Response())
    logged_in_client.post('/repos/alice/app/branches/old/delete')
    with app.app_context():
        entry = dict(get_db().execute('SELECT * FROM audit_log').fetchone())
    assert (entry['action'], entry['repo'], entry['target'], entry['ok']) == ('branch.delete', 'alice/app', 'old', 1)
