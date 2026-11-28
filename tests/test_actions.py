"""Tests for the GitHub Actions panel (issue #45). GitHub is never contacted."""
import base64
import pytest
import requests
from nacl import encoding, public
from werkzeug.datastructures import MultiDict

from app.controllers import actions_controller
from app.controllers.actions_controller import (
    encrypt_secret, get_logs_url, parse_dispatch_inputs, parse_page, run_action, run_state, set_secret,
    validate_dispatch, validate_secret,
)
from app.routes import actions_routes

REPO = '/repos/alice/app'
WORKFLOW = {'id': 11, 'name': 'CI', 'path': '.github/workflows/ci.yml', 'state': 'active'}
WORKFLOW_YAML = b"""
name: CI
on:
  push:
  workflow_dispatch:
    inputs:
      environment:
        description: Where to deploy
        type: choice
        options: [staging, production]
        required: true
      dry_run:
        type: boolean
        default: true
      retries:
        type: number
      note:
        description: Free text
"""


def run(run_id=5, **fields):
    data = {'id': run_id, 'name': 'CI', 'display_title': 'Fix <bug>', 'run_number': 42, 'run_attempt': 1,
            'status': 'completed', 'conclusion': 'failure', 'event': 'push', 'head_branch': 'main',
            'head_sha': 'abcdef1234567', 'html_url': 'https://github.com/alice/app/actions/runs/5',
            'workflow_id': 11, 'actor': {'login': 'bob'}, 'run_started_at': '2026-11-20T10:00:00Z'}
    data.update(fields)
    return data


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: responses by (method, path); every call is recorded."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json'), kwargs.get('params')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(actions_controller, 'github_api', fake_api)
    monkeypatch.setattr(actions_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(actions_routes, 'list_branches', lambda o, r, t: ([{'name': 'main'}, {'name': 'dev'}], None))
    monkeypatch.setattr(actions_routes, 'get_repository', lambda o, r, t: ({'default_branch': 'main'}, None))
    state['responses'][('GET', f'{REPO}/actions/workflows')] = ({'workflows': [WORKFLOW]}, None)
    return state


def flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


def workflow_file(github, content=WORKFLOW_YAML, ref='main'):
    github['responses'][('GET', f'{REPO}/contents/.github/workflows/ci.yml')] = (
        {'encoding': 'base64', 'size': len(content), 'content': base64.b64encode(content).decode()}, None)


# --- Display -----------------------------------------------------------------

@pytest.mark.parametrize('item, expected', [
    ({'status': 'completed', 'conclusion': 'success'}, ('success', 'success')),
    ({'status': 'completed', 'conclusion': 'failure'}, ('failure', 'danger')),
    ({'status': 'completed', 'conclusion': 'timed_out'}, ('timed out', 'danger')),
    ({'status': 'completed', 'conclusion': 'cancelled'}, ('cancelled', 'secondary')),
    ({'status': 'in_progress', 'conclusion': None}, ('in progress', 'warning')),
    ({'status': 'queued'}, ('queued', 'secondary')),
])
def test_run_state(item, expected):
    assert run_state(item) == expected


def test_parse_page():
    assert [parse_page(v) for v in ('2', '0', 'x', None, '99')] == [2, 1, 1, 1, 34]


# --- Run actions -------------------------------------------------------------

def test_rerun_failed_jobs(github):
    github['responses'][('POST', f'{REPO}/actions/runs/5/rerun-failed-jobs')] = (None, None)
    assert run_action('alice', 'app', run(), 'rerun_failed', 'tok') == ("Re-running failed jobs.", None)


@pytest.mark.parametrize('run_fields, action, message', [
    ({'status': 'completed', 'conclusion': 'success'}, 'rerun_failed', 'no failed jobs'),
    ({'status': 'in_progress', 'conclusion': None}, 'rerun', 'Wait for the run to finish'),
    ({'status': 'completed'}, 'cancel', 'already finished'),
    ({}, 'delete', 'Unknown action'),
])
def test_run_actions_are_checked_first(github, run_fields, action, message):
    _, error = run_action('alice', 'app', run(**run_fields), action, 'tok')
    assert message in error
    assert github['calls'] == []


def test_cancel_running(github):
    github['responses'][('POST', f'{REPO}/actions/runs/5/cancel')] = ({}, None)
    assert run_action('alice', 'app', run(status='in_progress', conclusion=None), 'cancel', 'tok')[0] == \
        "Cancelling the run."


class FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ''

    def json(self):
        return {'message': 'Not Found'}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)


def test_logs_url_is_taken_from_the_redirect(monkeypatch):
    seen = {}

    def fake_get(url, allow_redirects, timeout, headers):
        seen.update(url=url, allow_redirects=allow_redirects)
        return FakeResponse(302, {'Location': 'https://pipelines.example/logs.zip?sig=x'})

    monkeypatch.setattr(actions_controller.github_http, 'get', fake_get)
    assert get_logs_url('alice', 'app', 5, 'tok') == ('https://pipelines.example/logs.zip?sig=x', None)
    assert seen == {'url': 'https://api.github.com/repos/alice/app/actions/runs/5/logs', 'allow_redirects': False}


def test_logs_errors(monkeypatch):
    monkeypatch.setattr(actions_controller.github_http, 'get', lambda *a, **k: FakeResponse(404))
    assert get_logs_url('alice', 'app', 5, 'tok') == (None, 'Not Found')
    monkeypatch.setattr(actions_controller.github_http, 'get',
                        lambda *a, **k: FakeResponse(302, {'Location': 'http://insecure.example/x'}))
    assert get_logs_url('alice', 'app', 5, 'tok')[1] == "GitHub didn't return a download link."


# --- Dispatch inputs ---------------------------------------------------------

def test_parse_dispatch_inputs():
    import yaml
    inputs = parse_dispatch_inputs(yaml.safe_load(WORKFLOW_YAML))
    assert [i['name'] for i in inputs] == ['environment', 'dry_run', 'retries', 'note']
    assert inputs[0] == {'name': 'environment', 'description': 'Where to deploy', 'required': True, 'default': '',
                         'type': 'choice', 'options': ['staging', 'production']}
    assert inputs[1]['default'] == 'true' and inputs[1]['type'] == 'boolean'
    assert inputs[3]['type'] == 'string'


@pytest.mark.parametrize('document, expected', [
    ({True: 'workflow_dispatch'}, []),          # `on: workflow_dispatch` (YAML reads `on` as True)
    ({'on': ['push', 'workflow_dispatch']}, []),
    ({'on': {'workflow_dispatch': None}}, []),
    ({'on': ['push']}, None),
    ({'on': {'push': {}}}, None),
    ('not a mapping', None),
])
def test_dispatch_trigger_forms(document, expected):
    assert parse_dispatch_inputs(document) == expected


def test_validate_dispatch():
    import yaml
    inputs = parse_dispatch_inputs(yaml.safe_load(WORKFLOW_YAML))
    body, error = validate_dispatch(MultiDict({'ref': 'dev', 'input_environment': 'staging', 'input_retries': '3',
                                               'input_note': '', 'input_unknown': 'x'}), inputs, ['main', 'dev'])
    assert error is None
    assert body == {'ref': 'dev', 'inputs': {'environment': 'staging', 'dry_run': 'false', 'retries': '3'}}


@pytest.mark.parametrize('fields, message', [
    ({'ref': 'nope', 'input_environment': 'staging'}, 'Choose the branch'),
    ({'ref': 'main'}, "'environment' is required"),
    ({'ref': 'main', 'input_environment': 'moon'}, 'Choose one of the options'),
    ({'ref': 'main', 'input_environment': 'staging', 'input_retries': 'many'}, 'must be a number'),
])
def test_invalid_dispatch(fields, message):
    import yaml
    inputs = parse_dispatch_inputs(yaml.safe_load(WORKFLOW_YAML))
    assert message in validate_dispatch(MultiDict(fields), inputs, ['main', 'dev'])[1]


# --- Secrets -----------------------------------------------------------------

def test_validate_secret():
    assert validate_secret(' deploy_token ', 'x') == ('DEPLOY_TOKEN', None)
    for bad in ('', '1ABC', 'HAS-DASH', 'A B', 'x' * 101):
        assert validate_secret(bad, 'x')[0] is None, bad
    assert "can't start with GITHUB_" in validate_secret('github_token', 'x')[1]
    assert validate_secret('A', '')[1] == "Enter a value for the secret."
    assert '48 KB' in validate_secret('A', 'x' * (48 * 1024 + 1))[1]


def test_secret_is_encrypted_with_repository_key():
    private_key = public.PrivateKey.generate()
    key_b64 = private_key.public_key.encode(encoding.Base64Encoder()).decode()
    sealed = encrypt_secret(key_b64, 's3cr3t value')
    assert 's3cr3t' not in sealed
    assert public.SealedBox(private_key).decrypt(base64.b64decode(sealed)) == b's3cr3t value'


def test_set_secret_sends_only_ciphertext(github):
    private_key = public.PrivateKey.generate()
    github['responses'][('GET', f'{REPO}/actions/secrets/public-key')] = (
        {'key_id': 'k1', 'key': private_key.public_key.encode(encoding.Base64Encoder()).decode()}, None)
    github['responses'][('PUT', f'{REPO}/actions/secrets/DEPLOY_TOKEN')] = (None, None)
    assert set_secret('alice', 'app', 'DEPLOY_TOKEN', 'hunter2', 'tok') is None
    body = github['calls'][-1][2]
    assert body['key_id'] == 'k1' and 'hunter2' not in str(body)
    assert public.SealedBox(private_key).decrypt(base64.b64decode(body['encrypted_value'])) == b'hunter2'


def test_unusable_public_key(github):
    github['responses'][('GET', f'{REPO}/actions/secrets/public-key')] = ({'key_id': 'k1', 'key': 'not-a-key'}, None)
    assert set_secret('alice', 'app', 'A', 'v', 'tok') == "GitHub returned an unusable encryption key."
    assert not any(call[0] == 'PUT' for call in github['calls'])


def test_github_api_accepts_empty_success_bodies(monkeypatch):
    # e.g. PUT /actions/secrets/{name} answers 201 with no body
    from app.controllers import repo_controller

    class Empty:
        status_code, content = 201, b''

        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError('no JSON')

    monkeypatch.setattr(repo_controller.github_http, 'request', lambda *a, **k: Empty())
    assert repo_controller.github_api('PUT', '/x', 'tok') == (None, None)


# --- Routes ------------------------------------------------------------------

def test_overview_lists_workflows_and_runs(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/actions/runs')] = ({'total_count': 31, 'workflow_runs': [run()]}, None)
    html = logged_in_client.get('/repos/alice/app/actions').data.decode()
    assert 'CI' in html and 'Fix &lt;bug&gt;' in html and 'failure' in html
    assert '/repos/alice/app/actions/runs/5' in html
    assert 'page=2' in html  # 31 runs -> a second page


def test_overview_filters_by_workflow_and_status(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/actions/workflows/11/runs')] = ({'total_count': 0, 'workflow_runs': []}, None)
    html = logged_in_client.get('/repos/alice/app/actions?workflow=11&status=failure').data.decode()
    assert github['calls'][-1][3] == {'per_page': 30, 'page': 1, 'status': 'failure'}
    assert '/repos/alice/app/actions/workflows/11/dispatch' in html


def test_unknown_workflow_and_status_are_ignored(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/actions/runs')] = ({'total_count': 0, 'workflow_runs': []}, None)
    logged_in_client.get('/repos/alice/app/actions?workflow=999&status=evil')
    assert github['calls'][-1][1] == f'{REPO}/actions/runs'
    assert 'status' not in github['calls'][-1][3]


def test_run_page_shows_jobs_and_steps(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/actions/runs/5')] = (run(), None)
    github['responses'][('GET', f'{REPO}/actions/runs/5/jobs')] = ({'jobs': [
        {'name': 'test', 'status': 'completed', 'conclusion': 'failure', 'started_at': '2026-11-20T10:00:00Z',
         'completed_at': '2026-11-20T10:03:12Z', 'html_url': 'https://github.com/j/1',
         'steps': [{'number': 1, 'name': 'Checkout', 'status': 'completed', 'conclusion': 'success'}]}]}, None)
    html = logged_in_client.get('/repos/alice/app/actions/runs/5').data.decode()
    assert '3m 12s' in html and 'Checkout' in html
    assert 'value="rerun_failed"' in html and 'Download logs' in html and 'value="cancel"' not in html


def test_run_action_route(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/actions/runs/5')] = (run(), None)
    github['responses'][('POST', f'{REPO}/actions/runs/5/rerun')] = ({}, None)
    response = logged_in_client.post('/repos/alice/app/actions/runs/5', data={'action': 'rerun'})
    assert response.headers['Location'].endswith('/repos/alice/app/actions/runs/5')
    assert flashes(logged_in_client) == [('success', 'Re-running all jobs.')]


def test_logs_route_redirects_to_github(logged_in_client, github, monkeypatch):
    monkeypatch.setattr(actions_routes, 'get_logs_url', lambda o, r, i, t: ('https://pipelines.example/l.zip', None))
    response = logged_in_client.get('/repos/alice/app/actions/runs/5/logs')
    assert response.status_code == 302 and response.headers['Location'] == 'https://pipelines.example/l.zip'


def test_dispatch_form_renders_inputs(logged_in_client, github):
    workflow_file(github)
    html = logged_in_client.get('/repos/alice/app/actions/workflows/11/dispatch').data.decode()
    assert '<option value="production" >production</option>' in html
    assert 'name="input_dry_run"' in html and 'checked' in html
    assert 'type="number"' in html


def test_dispatching_a_workflow(logged_in_client, github):
    workflow_file(github)
    github['responses'][('POST', f'{REPO}/actions/workflows/11/dispatches')] = (None, None)
    response = logged_in_client.post('/repos/alice/app/actions/workflows/11/dispatch', data={
        'ref': 'main', 'input_environment': 'production', 'input_dry_run': 'on'})
    assert response.headers['Location'].endswith('/repos/alice/app/actions?workflow=11')
    assert github['calls'][-1][2] == {'ref': 'main', 'inputs': {'environment': 'production', 'dry_run': 'true'}}


def test_workflow_without_dispatch_trigger(logged_in_client, github):
    workflow_file(github, b'on: [push]\njobs: {}\n')
    html = logged_in_client.get('/repos/alice/app/actions/workflows/11/dispatch').data.decode()
    assert "can't be run manually" in html and 'Run workflow on' not in html
    logged_in_client.post('/repos/alice/app/actions/workflows/11/dispatch', data={'ref': 'main'})
    assert not any(call[0] == 'POST' for call in github['calls'])


def test_invalid_yaml_is_reported(logged_in_client, github):
    workflow_file(github, b'on: [push\n')
    html = logged_in_client.get('/repos/alice/app/actions/workflows/11/dispatch').data.decode()
    assert "couldn&#39;t be read as YAML" in html or "couldn't be read as YAML" in html


def test_unknown_workflow_is_404(logged_in_client, github):
    assert logged_in_client.get('/repos/alice/app/actions/workflows/99/dispatch').status_code == 404


def test_secrets_page_lists_names(logged_in_client, github):
    github['responses'][('GET', f'{REPO}/actions/secrets')] = (
        {'secrets': [{'name': 'DEPLOY_TOKEN', 'updated_at': '2026-11-20T10:00:00Z'}]}, None)
    html = logged_in_client.get('/repos/alice/app/actions/secrets').data.decode()
    assert 'DEPLOY_TOKEN' in html and '${{ secrets.NAME }}' in html


def test_saving_a_secret_never_echoes_the_value(logged_in_client, github, monkeypatch):
    saved = []
    monkeypatch.setattr(actions_routes, 'set_secret', lambda o, r, n, v, t: saved.append((n, v)) or 'Bad credentials')
    response = logged_in_client.post('/repos/alice/app/actions/secrets', data={
        'action': 'set', 'name': 'deploy_token', 'value': 'hunter2'})
    assert response.status_code == 302
    assert saved == [('DEPLOY_TOKEN', 'hunter2')]
    assert flashes(logged_in_client) == [('error', "Couldn't save the secret: Bad credentials")]
    assert 'hunter2' not in str(flashes(logged_in_client))


def test_deleting_a_secret(logged_in_client, github):
    github['responses'][('DELETE', f'{REPO}/actions/secrets/OLD')] = (None, None)
    logged_in_client.post('/repos/alice/app/actions/secrets', data={'action': 'delete', 'name': 'OLD'})
    assert flashes(logged_in_client) == [('success', 'Secret OLD deleted.')]
    logged_in_client.post('/repos/alice/app/actions/secrets', data={'action': 'delete', 'name': '../x'})
    assert flashes(logged_in_client)[-1] == ('error', "Couldn't delete ../x: Invalid secret name.")


@pytest.mark.parametrize('url', ['/repos/alice/app/actions', '/repos/alice/app/actions/runs/5',
                                 '/repos/alice/app/actions/secrets', '/repos/alice/app/actions/workflows/11/dispatch'])
def test_pages_require_login(client, url):
    assert client.get(url).status_code == 403
