"""Tests for issue #54: token caching, the shared GitHub client (connection reuse, conditional
requests, rate limits), background jobs for bulk actions, and dark mode. GitHub is never contacted."""
import glob
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app import github_http, token_cache
from app.controllers import auth_controller, bulk_controller, jobs_controller, repo_controller
from app.controllers.bulk_controller import apply_bulk_action, validate_bulk_request
from app.controllers.jobs_controller import create_job, finish_job, get_job, list_jobs, save_progress, start_job
from app.db import get_db


class FakeResponse:
    def __init__(self, status=200, data=None, headers=None, content=None):
        self.status_code = status
        self._data = data
        self.headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.content = content if content is not None else (json.dumps(data).encode() if data is not None else b'')
        self.encoding = 'utf-8'
        self.url = 'https://api.github.com/x'
        self.request = None
        self.text = self.content.decode('utf-8', 'replace')

    def json(self):
        if self._data is None:
            raise ValueError('no json')
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class FakeSession:
    """Answers queued responses and records what was sent."""
    def __init__(self, *responses):
        self.responses = list(responses)
        self.sent = []

    def request(self, method, url, headers=None, **kwargs):
        self.sent.append({'method': method, 'url': url, 'headers': dict(headers or {}), **kwargs})
        return self.responses.pop(0)


@pytest.fixture
def fake_session(monkeypatch):
    def install(*responses):
        session = FakeSession(*responses)
        monkeypatch.setattr(github_http, 'session', lambda: session)
        return session
    return install


AUTH = {'Authorization': 'Bearer tok-a'}


# --- Installation token cache ----------------------------------------------------

@pytest.fixture
def token_endpoint(app, monkeypatch):
    calls = []

    def fake_post(url, headers, timeout):
        calls.append(url)
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        return FakeResponse(201, {'token': f'token-{len(calls)}', 'expires_at': expires})

    monkeypatch.setattr(auth_controller, 'get_jwt', lambda: 'jwt')
    monkeypatch.setattr(auth_controller.github_http, 'post', fake_post)
    return calls


def test_installation_token_is_reused(app, token_endpoint):
    with app.test_request_context():
        assert auth_controller.get_installation_access_token(7) == 'token-1'
        assert auth_controller.get_installation_access_token(7) == 'token-1'
        assert auth_controller.get_installation_access_token(8) == 'token-2'
    assert len(token_endpoint) == 2


def test_token_is_refreshed_shortly_before_expiry():
    now = 1_000_000
    token_cache.put(1, 'old', datetime.fromtimestamp(now + 3600, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), now=now)
    assert token_cache.get(1, now=now + 3600 - token_cache.REFRESH_MARGIN - 1) == 'old'
    assert token_cache.get(1, now=now + 3600 - token_cache.REFRESH_MARGIN + 1) is None


def test_token_without_expiry_uses_default_lifetime():
    token_cache.put(1, 'tok', None, now=0)
    assert token_cache.get(1, now=token_cache.DEFAULT_LIFETIME - token_cache.REFRESH_MARGIN - 1) == 'tok'
    assert token_cache.get(1, now=token_cache.DEFAULT_LIFETIME) is None


def test_rejected_token_is_forgotten(fake_session):
    token_cache.put(3, 'tok-a', None)
    fake_session(FakeResponse(401, {'message': 'Bad credentials'}))
    github_http.get('https://api.github.com/repos/a/b', headers=AUTH)
    assert token_cache.get(3) is None


def test_failed_token_exchange_is_not_cached(app, monkeypatch):
    monkeypatch.setattr(auth_controller, 'get_jwt', lambda: 'jwt')
    monkeypatch.setattr(auth_controller.github_http, 'post', lambda url, headers, timeout: FakeResponse(500, {}))
    with app.test_request_context():
        assert auth_controller.get_installation_access_token(7) is None
    assert token_cache.get(7) is None


# --- Shared session --------------------------------------------------------------

def test_session_is_shared_per_thread():
    assert github_http.session() is github_http.session()
    other = []
    thread = threading.Thread(target=lambda: other.append(github_http.session()))
    thread.start()
    thread.join()
    assert other[0] is not github_http.session()


def test_session_sends_identity_and_refuses_cookies():
    session = github_http.session()
    assert session.headers['User-Agent'] == 'RepoMaster'
    assert session.headers['X-GitHub-Api-Version'] == github_http.API_VERSION
    # No domain may set cookies, so nothing is carried from one user's request to another's
    assert tuple(session.cookies._policy.allowed_domains()) == ()
    cookie = requests.cookies.create_cookie('user_session', 'abc', domain='github.com')
    request = requests.cookies.MockRequest(requests.Request('GET', 'https://github.com/login').prepare())
    assert session.cookies._policy.set_ok(cookie, request) is False


def test_wrappers_pass_arguments_through(fake_session):
    session = fake_session(FakeResponse(201, {}))
    github_http.post('https://api.github.com/x', json={'a': 1}, timeout=5)
    assert session.sent == [{'method': 'POST', 'url': 'https://api.github.com/x', 'headers': {},
                             'json': {'a': 1}, 'timeout': 5}]


# --- Conditional requests ----------------------------------------------------------

def test_etag_is_used_and_304_returns_cached_body(fake_session):
    session = fake_session(
        FakeResponse(200, {'name': 'repo'}, {'ETag': '"v1"', 'Link': '<next>', 'X-RateLimit-Remaining': '4999'}),
        FakeResponse(304, None, {'ETag': '"v1"', 'X-RateLimit-Remaining': '4999'}))
    first = github_http.get('https://api.github.com/repos/a/b', headers=AUTH, params={'per_page': 100})
    second = github_http.get('https://api.github.com/repos/a/b', headers=AUTH, params={'per_page': 100})

    assert 'If-None-Match' not in session.sent[0]['headers']
    assert session.sent[1]['headers']['If-None-Match'] == '"v1"'
    assert (second.status_code, second.json(), second.headers['Link']) == (200, {'name': 'repo'}, '<next>')
    assert second.from_cache is True
    assert first.json() == second.json()


def test_changed_resource_replaces_cache(fake_session):
    session = fake_session(FakeResponse(200, {'v': 1}, {'ETag': '"v1"'}),
                           FakeResponse(200, {'v': 2}, {'ETag': '"v2"'}),
                           FakeResponse(304, None, {}))
    github_http.get('https://api.github.com/r', headers=AUTH)
    assert github_http.get('https://api.github.com/r', headers=AUTH).json() == {'v': 2}
    assert github_http.get('https://api.github.com/r', headers=AUTH).json() == {'v': 2}
    assert session.sent[2]['headers']['If-None-Match'] == '"v2"'


def test_cache_is_separate_per_token_params_and_accept(fake_session):
    session = fake_session(*[FakeResponse(200, {}, {'ETag': '"e"'}) for _ in range(4)])
    github_http.get('https://api.github.com/r', headers=AUTH)
    github_http.get('https://api.github.com/r', headers={'Authorization': 'Bearer tok-b'})
    github_http.get('https://api.github.com/r', headers=AUTH, params={'page': 2})
    github_http.get('https://api.github.com/r', headers={**AUTH, 'Accept': 'application/vnd.github.raw'})
    assert all('If-None-Match' not in sent['headers'] for sent in session.sent)


@pytest.mark.parametrize('method, headers, response', [
    ('POST', AUTH, FakeResponse(200, {}, {'ETag': '"e"'})),           # only GETs
    ('GET', {}, FakeResponse(200, {}, {'ETag': '"e"'})),              # only authenticated requests
    ('GET', AUTH, FakeResponse(200, {})),                             # nothing to revalidate with
    ('GET', AUTH, FakeResponse(404, {}, {'ETag': '"e"'})),            # only successes
    ('GET', AUTH, FakeResponse(200, None, {'ETag': '"e"'},
                               content=b'x' * (github_http.MAX_CACHED_BODY_BYTES + 1))),  # too big
])
def test_not_cached(fake_session, method, headers, response):
    session = fake_session(response, FakeResponse(200, {}))
    github_http.request(method, 'https://api.github.com/r', headers=headers)
    github_http.request(method, 'https://api.github.com/r', headers=headers)
    assert 'If-None-Match' not in session.sent[1]['headers']


def test_cache_evicts_least_recently_used(fake_session, monkeypatch):
    monkeypatch.setattr(github_http, 'MAX_CACHE_ENTRIES', 2)
    session = fake_session(*[FakeResponse(200, {}, {'ETag': f'"{n}"'}) for n in range(5)])
    for path in ('a', 'b', 'a', 'c', 'b'):
        github_http.get(f'https://api.github.com/{path}', headers=AUTH)
    # 'b' was evicted when 'c' came in ('a' had been used more recently)
    assert 'If-None-Match' in session.sent[2]['headers']      # a again
    assert 'If-None-Match' not in session.sent[4]['headers']  # b again


def test_github_api_benefits_from_cache(fake_session):
    fake_session(FakeResponse(200, [{'name': 'main'}], {'ETag': '"e"'}), FakeResponse(304, None, {}))
    assert repo_controller.github_api('GET', '/repos/a/b/branches', 'tok') == ([{'name': 'main'}], None)
    assert repo_controller.github_api('GET', '/repos/a/b/branches', 'tok') == ([{'name': 'main'}], None)


# --- Rate limits ------------------------------------------------------------------

def test_retry_delay():
    now = 1000
    assert github_http.retry_delay(FakeResponse(403, {}, {'Retry-After': '30'})) == 30
    assert github_http.retry_delay(FakeResponse(429, {}, {'Retry-After': '0'})) == 1
    assert github_http.retry_delay(FakeResponse(403, {}, {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '1120'}),
                                   now=now) == 121
    assert github_http.retry_delay(FakeResponse(403, {'message': 'You have exceeded a secondary rate limit.'})) == 60
    assert github_http.retry_delay(FakeResponse(403, {'message': 'Resource not accessible by integration'})) is None
    assert github_http.retry_delay(FakeResponse(404, {}, {'Retry-After': '30'})) is None


def test_rate_limit_message_in_github_api(fake_session):
    reset = int(datetime(2026, 11, 28, 15, 30, tzinfo=timezone.utc).timestamp())
    fake_session(FakeResponse(403, {'message': 'API rate limit exceeded'},
                              {'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': str(reset)}))
    assert repo_controller.github_api('GET', '/repos/a/b', 'tok') == (
        None, "GitHub's rate limit is used up. Try again after 15:30 UTC.")
    fake_session(FakeResponse(403, {'message': 'secondary rate limit'}, {'Retry-After': '20'}))
    assert repo_controller.github_api('GET', '/repos/a/b', 'tok')[1] == \
        "GitHub is limiting requests right now. Try again in 20 seconds."


def test_other_403s_keep_githubs_message(fake_session):
    fake_session(FakeResponse(403, {'message': 'Must have admin rights to Repository.'}))
    assert repo_controller.github_api('DELETE', '/repos/a/b', 'tok')[1] == 'Must have admin rights to Repository.'


def test_rate_limit_is_tracked_and_low_quota_logged_once(fake_session, caplog):
    fake_session(*[FakeResponse(200, {}, {'X-RateLimit-Remaining': str(n), 'X-RateLimit-Limit': '5000',
                                          'X-RateLimit-Reset': '2000'}) for n in (50, 49)])
    with caplog.at_level(logging.WARNING):
        github_http.get('https://api.github.com/a')
        github_http.get('https://api.github.com/b')
    assert github_http.rate_limit_status() == {'remaining': 49, 'limit': 5000, 'reset': 2000}
    assert sum('rate limit is low' in record.message for record in caplog.records) == 1


def test_rate_limited_response_is_reported_to_the_thread(fake_session):
    fake_session(FakeResponse(429, {}, {'Retry-After': '7'}))
    github_http.pop_rate_limited()
    github_http.get('https://api.github.com/a')
    assert github_http.pop_rate_limited() == 7
    assert github_http.pop_rate_limited() is None


# --- Bulk actions: progress and rate limits -----------------------------------------

def bulk(repos):
    request, error = validate_bulk_request('archive', repos)
    assert error is None
    return request


def test_bulk_retries_after_a_short_rate_limit(app, monkeypatch):
    attempts, slept = [], []

    def flaky(full_name, token, bulk_request, installation_id, actor):
        attempts.append((full_name, token))
        if len(attempts) == 1:
            github_http._local.rate_limited = 5
            return False, 'GitHub is limiting requests right now.'
        return True, 'Archived'

    monkeypatch.setattr(bulk_controller, '_apply_one', flaky)
    tokens = iter(['t1', 't2', 't3'])
    with app.app_context():
        results = apply_bulk_action(lambda: next(tokens), bulk(['alice/a', 'alice/b']), installation_id=1,
                                    actor='alice', sleep=slept.append)
    assert slept == [5]
    assert [r['ok'] for r in results] == [True, True]
    assert attempts == [('alice/a', 't1'), ('alice/a', 't2'), ('alice/b', 't3')]


def test_bulk_stops_on_a_long_rate_limit(app, monkeypatch):
    def limited(full_name, *args):
        github_http._local.rate_limited = bulk_controller.MAX_RATE_LIMIT_WAIT + 1
        return False, "GitHub's rate limit is used up. Try again after 15:30 UTC."

    calls = []
    monkeypatch.setattr(bulk_controller, '_apply_one', lambda *a: calls.append(a[0]) or limited(*a))
    with app.app_context():
        results = apply_bulk_action('tok', bulk(['alice/a', 'alice/b', 'alice/c']), installation_id=1,
                                    actor='alice', sleep=lambda s: pytest.fail('must not wait that long'))
        audited = [row['repo'] for row in get_db().execute('SELECT repo FROM audit_log')]
    assert calls == ['alice/a']
    assert [r['message'] for r in results[1:]] == [
        "Skipped: GitHub's rate limit is used up. Try again after 15:30 UTC."] * 2
    assert audited == ['alice/a']


def test_bulk_failures_without_rate_limit_are_not_retried(app, monkeypatch):
    calls = []
    monkeypatch.setattr(bulk_controller, '_apply_one', lambda *a: calls.append(a[0]) or (False, 'Not Found'))
    with app.app_context():
        apply_bulk_action('tok', bulk(['alice/a']), installation_id=1, actor='alice',
                          sleep=lambda s: pytest.fail('no wait'))
    assert calls == ['alice/a']


def test_bulk_reports_progress_and_audits_without_a_session(app, monkeypatch):
    monkeypatch.setattr(bulk_controller, 'update_repository', lambda owner, repo, token, fields: ({}, None))
    seen = []
    with app.app_context():
        apply_bulk_action('tok', bulk(['alice/a', 'alice/b']), installation_id=9, actor='bob', on_progress=seen.append)
        rows = [dict(row) for row in get_db().execute('SELECT installation_id, actor, repo FROM audit_log')]
    assert [r['repo'] for r in seen] == ['alice/a', 'alice/b']
    assert rows == [{'installation_id': 9, 'actor': 'bob', 'repo': 'alice/a'},
                    {'installation_id': 9, 'actor': 'bob', 'repo': 'alice/b'}]


# --- Jobs -------------------------------------------------------------------------

def test_job_lifecycle_and_scoping(app):
    with app.app_context():
        job_id = create_job(1, 'alice', 'bulk', 'Archive 2 repositories', 2)
        job = get_job(job_id, 1)
        assert (job['status'], job['done'], job['percent'], job['active']) == ('queued', 0, 0, True)
        save_progress(job_id, [{'repo': 'alice/a', 'ok': True, 'message': 'Archived'}])
        job = get_job(job_id, 1)
        assert (job['status'], job['done'], job['percent'], job['succeeded']) == ('running', 1, 50, 1)
        finish_job(job_id, job['results'] + [{'repo': 'alice/b', 'ok': False, 'message': 'Not Found'}])
        job = get_job(job_id, 1)
        assert (job['status'], job['done'], job['succeeded'], job['active']) == ('finished', 2, 1, False)
        assert job['finished_at']
        assert get_job(job_id, 2) is None
        assert [j['id'] for j in list_jobs(1)] == [job_id] and list_jobs(2) == []


def test_job_without_progress_shows_as_interrupted(app):
    with app.app_context():
        job_id = create_job(1, 'alice', 'bulk', 'Archive', 3)
        later = datetime.now(timezone.utc) + jobs_controller.STALE_AFTER + timedelta(minutes=1)
        job = get_job(job_id, 1, now=later)
        assert (job['status'], job['status_label'], job['active']) == ('interrupted', 'Interrupted', False)


def test_crashing_job_is_marked_failed_keeping_results(app):
    def crash(job_id):
        save_progress(job_id, [{'repo': 'alice/a', 'ok': True, 'message': 'Archived'}])
        raise RuntimeError('boom')

    with app.app_context():
        job_id = create_job(1, 'alice', 'bulk', 'Archive', 2)
        start_job(job_id, crash)
        job = get_job(job_id, 1)
    assert job['status'] == 'failed' and job['done'] == 1
    assert 'unexpected error' in job['error']


def test_jobs_run_in_a_background_thread(app):
    app.config['BACKGROUND_JOBS_SYNC'] = False
    release = threading.Event()
    ran_in = []

    def work(job_id):
        release.wait(5)
        ran_in.append(threading.current_thread().name)
        finish_job(job_id, [])

    with app.app_context():
        job_id = create_job(1, 'alice', 'bulk', 'Archive', 0)
        start_job(job_id, work)
        assert get_job(job_id, 1)['status'] == 'queued'  # the request didn't wait
    release.set()
    thread = next(t for t in threading.enumerate() if t.name == f'repomaster-job-{job_id}')
    thread.join(5)
    with app.app_context():
        assert get_job(job_id, 1)['status'] == 'finished'
    assert ran_in == [f'repomaster-job-{job_id}']


# --- Job pages ----------------------------------------------------------------------

def test_bulk_apply_runs_as_job_end_to_end(app, logged_in_client, monkeypatch):
    monkeypatch.setattr('app.routes.bulk_routes.get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(bulk_controller, 'get_installation_access_token', lambda installation_id: 'tok')
    monkeypatch.setattr(bulk_controller, 'update_repository',
                        lambda owner, repo, token, fields: ({}, None) if repo == 'one' else (None, 'Not Found'))
    response = logged_in_client.post('/repositories/bulk/apply', data={'action': 'archive',
                                                                        'repos': ['alice/one', 'alice/two']})
    assert response.status_code == 302
    html = logged_in_client.get(response.headers['Location']).data.decode()
    assert 'Bulk Action Results' in html
    assert '1 of 2 repositories updated, 1 failed.' in html
    assert 'Not Found' in html and 'job_progress' not in html
    with app.app_context():
        assert [row['actor'] for row in get_db().execute('SELECT actor FROM audit_log')] == ['alice', 'alice']


def test_running_job_page_polls_progress(app, logged_in_client):
    with app.app_context():
        job_id = create_job(1, 'alice', 'bulk', 'Archive 4 repositories', 4)
        save_progress(job_id, [{'repo': 'alice/a', 'ok': True, 'message': 'Archived'}])
    html = logged_in_client.get(f'/jobs/{job_id}').data.decode()
    assert 'Bulk Action Progress' in html and '1 of 4' in html
    assert f'"/jobs/{job_id}/progress"' in html
    assert 'http-equiv="refresh"' in html
    data = logged_in_client.get(f'/jobs/{job_id}/progress').get_json()
    assert data == {'status': 'running', 'status_label': 'Running', 'active': True, 'done': 1, 'total': 4,
                    'percent': 25, 'succeeded': 1}


def test_job_pages_are_per_installation(app, logged_in_client):
    with app.app_context():
        job_id = create_job(2, 'carol', 'bulk', 'Other account job', 1)
    assert logged_in_client.get(f'/jobs/{job_id}').status_code == 404
    assert logged_in_client.get(f'/jobs/{job_id}/progress').status_code == 404
    assert 'Other account job' not in logged_in_client.get('/jobs').data.decode()


def test_jobs_list(app, logged_in_client):
    with app.app_context():
        finish_job(create_job(1, 'alice', 'bulk', 'Make private: 3 repositories', 3), [])
    html = logged_in_client.get('/jobs').data.decode()
    assert 'Make private: 3 repositories' in html and 'Finished' in html


def test_job_pages_require_login(client):
    for url in ('/jobs', '/jobs/1', '/jobs/1/progress'):
        assert client.get(url).status_code == 403


# --- Dark mode ------------------------------------------------------------------------

TEMPLATES = os.path.join(os.path.dirname(__file__), '..', 'app', 'templates')


def test_every_bootstrap_page_includes_the_theme():
    pages = [p for p in glob.glob(os.path.join(TEMPLATES, '*.html')) if not os.path.basename(p).startswith('_')]
    bootstrap_pages = [p for p in pages if 'bootstrap@5.3.0/dist/css/bootstrap.min.css' in open(p, encoding='utf-8').read()]
    assert len(bootstrap_pages) >= 40
    for page in bootstrap_pages:
        head = open(page, encoding='utf-8').read().split('</head>')[0]
        assert "{% include '_theme.html' %}" in head, page


def test_theme_files_are_served(client):
    js = client.get('/static/js/theme.js')
    assert js.status_code == 200 and b'data-bs-theme' in js.data and b'localStorage' in js.data
    assert client.get('/static/css/theme.css').status_code == 200


def test_rendered_page_loads_theme_in_head(logged_in_client, monkeypatch):
    monkeypatch.setattr('app.routes.repo_routes.get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr('app.routes.repo_routes.get_github_repositories', lambda token: [])
    head = logged_in_client.get('/github/repositories').data.decode().split('</head>')[0]
    assert '/static/js/theme.js' in head and '/static/css/theme.css' in head
