"""Tests for bulk repository actions (issue #35). GitHub is never contacted."""
import pytest
import requests

from app.controllers import bulk_controller, repo_controller
from app.controllers.bulk_controller import (
    apply_bulk_action, describe_bulk_request, parse_topics, validate_bulk_request,
)
from app.routes import bulk_routes


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
def github(monkeypatch):
    """
    Fake GitHub repository endpoints. Records every call; `fail` maps a repo
    full name to (status, message) to make calls for that repo fail.
    """
    state = {
        'calls': [],
        'topics': {'alice/one': ['python'], 'alice/two': []},
        'fail': {},
    }

    def repo_of(url):
        parts = url.split('/repos/', 1)[1].split('/')
        return f"{parts[0]}/{parts[1]}"

    def maybe_fail(url):
        failure = state['fail'].get(repo_of(url))
        if failure:
            return FakeResponse(failure[0], {'message': failure[1]})
        return None

    def fake_patch(url, headers, json, timeout):
        state['calls'].append(('PATCH', repo_of(url), json))
        return maybe_fail(url) or FakeResponse(200, {'full_name': repo_of(url)})

    def fake_get(url, headers, timeout):
        state['calls'].append(('GET', repo_of(url), None))
        return maybe_fail(url) or FakeResponse(200, {'names': list(state['topics'].get(repo_of(url), []))})

    def fake_put(url, headers, json, timeout):
        state['calls'].append(('PUT', repo_of(url), json))
        state['topics'][repo_of(url)] = json['names']
        return maybe_fail(url) or FakeResponse(200, {'names': json['names']})

    monkeypatch.setattr(repo_controller.github_http, 'patch', fake_patch)
    monkeypatch.setattr(repo_controller.github_http, 'get', fake_get)
    monkeypatch.setattr(repo_controller.github_http, 'put', fake_put)
    return state


def bulk(action, repos=('alice/one',), topics='', branch=''):
    bulk_request, error = validate_bulk_request(action, list(repos), topics, branch)
    assert error is None, error
    return bulk_request


# --- Validation --------------------------------------------------------------

def test_parse_topics_normalises_and_dedupes():
    assert parse_topics(' Python, flask  cli,python ') == (['python', 'flask', 'cli'], None)


@pytest.mark.parametrize('raw', ['', '  , ', 'bad_topic', '-leading', 'a' * 51, 'Ünïcode'])
def test_parse_topics_rejects_invalid(raw):
    topics, error = parse_topics(raw)
    assert topics is None and error


def test_parse_topics_rejects_more_than_twenty():
    assert parse_topics(' '.join(f't{i}' for i in range(21)))[0] is None


@pytest.mark.parametrize('action, repos, topics, branch, message', [
    ('explode', ['alice/one'], '', '', 'Choose an action'),
    ('archive', [], '', '', 'Select at least one'),
    ('archive', ['not a repo'], '', '', 'Invalid repository'),
    ('archive', ['../etc/passwd'], '', '', 'Invalid repository'),
    ('add_topics', ['alice/one'], '', '', 'at least one topic'),
    ('set_default_branch', ['alice/one'], '', '', 'Enter the branch'),
    ('set_default_branch', ['alice/one'], '', 'bad..name', 'not a valid branch'),
    ('set_default_branch', ['alice/one'], '', 'has space', 'not a valid branch'),
    ('set_default_branch', ['alice/one'], '', 'release.lock', 'not a valid branch'),
])
def test_validate_bulk_request_errors(action, repos, topics, branch, message):
    bulk_request, error = validate_bulk_request(action, repos, topics, branch)
    assert bulk_request is None
    assert message in error


def test_validate_bulk_request_dedupes_repos_and_accepts_nested_branch():
    bulk_request = bulk('set_default_branch', ['alice/one', 'alice/one', 'org/two'], branch='release/2.0')
    assert bulk_request['repos'] == ['alice/one', 'org/two']
    assert bulk_request['branch'] == 'release/2.0'


def test_describe_bulk_request():
    assert describe_bulk_request(bulk('add_topics', topics='a b')) == 'Add topics: a, b'
    assert describe_bulk_request(bulk('set_default_branch', branch='main')) == "Change the default branch to 'main'"
    assert describe_bulk_request(bulk('archive')) == 'Archive (make read-only)'


# --- Applying actions --------------------------------------------------------

@pytest.mark.parametrize('action, fields', [
    ('archive', {'archived': True}),
    ('unarchive', {'archived': False}),
    ('make_private', {'private': True}),
    ('make_public', {'private': False}),
])
def test_simple_actions_patch_the_repository(github, action, fields):
    results = apply_bulk_action('tok', bulk(action, repos=['alice/one', 'alice/two']))

    assert github['calls'] == [('PATCH', 'alice/one', fields), ('PATCH', 'alice/two', fields)]
    assert all(r['ok'] for r in results)


def test_set_default_branch(github):
    apply_bulk_action('tok', bulk('set_default_branch', branch='main'))
    assert github['calls'] == [('PATCH', 'alice/one', {'default_branch': 'main'})]


def test_add_topics_merges_with_existing(github):
    results = apply_bulk_action('tok', bulk('add_topics', repos=['alice/one', 'alice/two'], topics='python flask'))

    assert github['topics'] == {'alice/one': ['python', 'flask'], 'alice/two': ['python', 'flask']}
    assert all(r['ok'] for r in results)


def test_remove_topics(github):
    apply_bulk_action('tok', bulk('remove_topics', topics='python'))
    assert github['topics']['alice/one'] == []


def test_topics_unchanged_skips_the_update(github):
    results = apply_bulk_action('tok', bulk('add_topics', topics='python'))

    assert [call[0] for call in github['calls']] == ['GET']
    assert results[0] == {'repo': 'alice/one', 'ok': True, 'message': 'No change needed'}


def test_topic_limit_is_checked_per_repository(github):
    github['topics']['alice/one'] = [f'existing-{i}' for i in range(19)]

    results = apply_bulk_action('tok', bulk('add_topics', topics='new-a new-b'))

    assert not results[0]['ok']
    assert 'limit of 20' in results[0]['message']
    assert [call[0] for call in github['calls']] == ['GET']


def test_one_failure_does_not_stop_the_rest(github):
    github['fail']['alice/one'] = (403, 'Repository was archived so is read-only.')

    results = apply_bulk_action('tok', bulk('make_private', repos=['alice/one', 'alice/two']))

    assert results == [
        {'repo': 'alice/one', 'ok': False, 'message': 'Repository was archived so is read-only.'},
        {'repo': 'alice/two', 'ok': True, 'message': 'Made private'},
    ]


def test_network_error_is_reported(monkeypatch):
    def offline(*args, **kwargs):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(repo_controller.github_http, 'patch', offline)
    results = apply_bulk_action('tok', bulk('archive'))
    assert results == [{'repo': 'alice/one', 'ok': False, 'message': 'Could not reach GitHub'}]


# --- Routes ------------------------------------------------------------------

@pytest.mark.parametrize('method, url', [
    ('get', '/repositories/bulk'),
    ('post', '/repositories/bulk/confirm'),
    ('post', '/repositories/bulk/apply'),
])
def test_bulk_routes_require_login(client, method, url):
    assert getattr(client, method)(url).status_code == 403


@pytest.fixture
def fake_token(monkeypatch):
    monkeypatch.setattr(bulk_routes, 'get_installation_access_token', lambda: 'tok')


def test_bulk_page_lists_repositories_and_actions(logged_in_client, fake_token, monkeypatch):
    monkeypatch.setattr(bulk_routes, 'get_github_repositories', lambda token: [
        {'full_name': 'alice/one', 'private': True, 'archived': True, 'default_branch': 'main',
         'topics': ['python'], 'description': 'First repo'},
    ])

    response = logged_in_client.get('/repositories/bulk')

    assert response.status_code == 200
    assert b'value="alice/one"' in response.data
    assert b'Archived' in response.data
    for key in bulk_controller.ACTIONS:
        assert f'value="{key}"'.encode() in response.data


def test_confirm_lists_every_repository_without_changing_anything(logged_in_client, monkeypatch):
    monkeypatch.setattr(bulk_controller, 'apply_bulk_action', lambda *a, **k: pytest.fail("must not apply on confirm"))

    response = logged_in_client.post('/repositories/bulk/confirm', data={
        'action': 'add_topics', 'topics': 'flask', 'repos': ['alice/one', 'org/two'],
    })

    assert response.status_code == 200
    assert b'Add topics: flask' in response.data
    assert b'<code>alice/one</code>' in response.data
    assert b'<code>org/two</code>' in response.data
    assert b'Apply to 2 repositories' in response.data


def test_confirm_with_invalid_input_goes_back_with_message(logged_in_client):
    response = logged_in_client.post('/repositories/bulk/confirm', data={'action': 'archive'},
                                     follow_redirects=False)
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/repositories/bulk')
    with logged_in_client.session_transaction() as sess:
        assert sess['_flashes'] == [('danger', 'Select at least one repository.')]


def test_apply_runs_the_action_and_shows_report(logged_in_client, fake_token, monkeypatch):
    received = {}

    def fake_apply(token, bulk_request, installation_id, actor, on_progress):
        received.update(token=token(), bulk_request=bulk_request, installation_id=installation_id, actor=actor)
        results = [{'repo': 'alice/one', 'ok': True, 'message': 'Archived'},
                   {'repo': 'alice/two', 'ok': False, 'message': 'Not Found'}]
        for result in results:
            on_progress(result)
        return results

    monkeypatch.setattr(bulk_controller, 'apply_bulk_action', fake_apply)
    monkeypatch.setattr(bulk_controller, 'get_installation_access_token', lambda installation_id: 'tok')

    response = logged_in_client.post('/repositories/bulk/apply', data={
        'action': 'archive', 'repos': ['alice/one', 'alice/two'],
    })
    assert response.status_code == 302 and response.headers['Location'].startswith('/jobs/')
    response = logged_in_client.get(response.headers['Location'])

    assert received['token'] == 'tok'
    assert received['bulk_request']['repos'] == ['alice/one', 'alice/two']
    assert (received['installation_id'], received['actor']) == (1, 'alice')
    assert b'1 of 2 repositories updated, 1 failed.' in response.data
    assert b'Not Found' in response.data


def test_apply_revalidates_input(logged_in_client, monkeypatch):
    monkeypatch.setattr(bulk_controller, 'apply_bulk_action', lambda *a, **k: pytest.fail("must not apply invalid input"))
    response = logged_in_client.post('/repositories/bulk/apply', data={
        'action': 'set_default_branch', 'branch': 'bad..name', 'repos': ['alice/one'],
    })
    assert response.status_code == 302
