"""Tests for reviewing and merging pull requests (issue #40). GitHub is never contacted."""
import pytest
from werkzeug.datastructures import MultiDict

from app.controllers import pull_requests_controller
from app.controllers.pull_requests_controller import (
    allowed_merge_methods, apply_pull_request_action, can_delete_head_branch, diff_lines,
    merge_status, summarize_checks, summarize_reviews, validate_pull_request_action,
)
from app.routes import pull_request_routes

BASE = '/repos/alice/app/pulls'
SHA = 'abc123'


def pull(number=5, **fields):
    repo = {'full_name': 'alice/app', 'default_branch': 'main'}
    data = {
        'number': number, 'title': f'PR {number}', 'body': 'Adds a feature', 'state': 'open', 'merged': False,
        'draft': False, 'mergeable': True, 'mergeable_state': 'clean', 'user': {'login': 'bob'},
        'html_url': f'https://github.com/alice/app/pull/{number}', 'created_at': '2026-11-20T10:00:00Z',
        'head': {'ref': 'feature', 'label': 'alice:feature', 'sha': SHA, 'repo': dict(repo)},
        'base': {'ref': 'main', 'repo': dict(repo)},
        'commits': 2, 'additions': 10, 'deletions': 3, 'changed_files': 1,
    }
    data.update(fields)
    return data


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: responses are looked up by (method, path); every call is recorded."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(pull_requests_controller, 'github_api', fake_api)
    monkeypatch.setattr(pull_request_routes, 'get_installation_access_token', lambda: 'tok')
    return state


def form(**fields):
    return MultiDict(fields)


def flashes(client):
    with client.session_transaction() as sess:
        return sess.get('_flashes', [])


# --- Summaries ---------------------------------------------------------------

def test_diff_lines_are_classified():
    patch = '@@ -1,2 +1,2 @@\n context\n-old\n+new'
    assert diff_lines(patch) == [('hunk', '@@ -1,2 +1,2 @@'), ('', ' context'), ('del', '-old'), ('add', '+new')]
    assert diff_lines(None) == []


def test_summarize_checks():
    assert summarize_checks([])['state'] == 'none'
    runs = [{'status': 'completed', 'conclusion': 'success'}, {'status': 'completed', 'conclusion': 'skipped'}]
    assert summarize_checks(runs) == {'state': 'success', 'success': 1, 'failure': 0, 'pending': 0, 'skipped': 1}
    assert summarize_checks(runs + [{'status': 'in_progress'}])['state'] == 'pending'
    assert summarize_checks(runs + [{'status': 'in_progress'},
                                    {'status': 'completed', 'conclusion': 'timed_out'}])['state'] == 'failure'


def test_summarize_reviews_uses_each_reviewers_latest_decision():
    reviews = [
        {'user': {'login': 'carol'}, 'state': 'CHANGES_REQUESTED'},
        {'user': {'login': 'carol'}, 'state': 'COMMENTED'},
        {'user': {'login': 'carol'}, 'state': 'APPROVED'},
        {'user': {'login': 'dave'}, 'state': 'APPROVED'},
        {'user': {'login': 'dave'}, 'state': 'DISMISSED'},
        {'user': {'login': 'erin'}, 'state': 'CHANGES_REQUESTED'},
        {'user': {'login': 'erin'}, 'state': 'COMMENTED'},
    ]
    assert summarize_reviews(reviews) == {'approved': ['carol'], 'changes_requested': ['erin']}


@pytest.mark.parametrize('fields, level, text', [
    ({'merged': True}, 'info', 'has been merged'),
    ({'state': 'closed'}, 'secondary', 'is closed'),
    ({'draft': True}, 'secondary', 'draft'),
    ({'mergeable': None}, 'secondary', 'still checking'),
    ({'mergeable': False, 'mergeable_state': 'dirty'}, 'danger', 'merge conflicts'),
    ({'mergeable_state': 'blocked'}, 'warning', 'branch protection'),
    ({'mergeable_state': 'behind'}, 'warning', 'behind'),
    ({'mergeable_state': 'unstable'}, 'warning', 'checks are failing'),
    ({}, 'success', 'no conflicts'),
])
def test_merge_status(fields, level, text):
    got_level, message = merge_status(pull(**fields))
    assert got_level == level and text in message


def test_allowed_merge_methods_follow_repository_settings():
    pr = pull()
    pr['base']['repo'].update(allow_merge_commit=False, allow_squash_merge=True, allow_rebase_merge=False)
    assert list(allowed_merge_methods(pr)) == ['squash']
    assert list(allowed_merge_methods(pull())) == ['merge', 'squash', 'rebase']


def test_head_branch_deletable_only_for_same_repo_non_default_branch():
    assert can_delete_head_branch(pull())
    fork = pull()
    fork['head']['repo'] = {'full_name': 'mallory/app'}
    assert not can_delete_head_branch(fork)
    default = pull()
    default['head']['ref'] = 'main'
    assert not can_delete_head_branch(default)
    deleted_fork = pull()
    deleted_fork['head']['repo'] = None
    assert not can_delete_head_branch(deleted_fork)


# --- Validation --------------------------------------------------------------

def test_merge_payload_includes_method_sha_and_commit_text():
    spec, error = validate_pull_request_action('merge', form(
        merge_method='squash', sha=SHA, commit_title=' Feature (#5) ', commit_message='Details', delete_branch='on'), pull())
    assert error is None
    assert spec == {'action': 'merge', 'delete_branch': True, 'payload': {
        'merge_method': 'squash', 'sha': SHA, 'commit_title': 'Feature (#5)', 'commit_message': 'Details'}}


def test_rebase_ignores_commit_text_and_forks_never_delete_branch():
    fork = pull()
    fork['head']['repo'] = {'full_name': 'mallory/app'}
    spec, _ = validate_pull_request_action('merge', form(
        merge_method='rebase', sha=SHA, commit_title='x', delete_branch='on'), fork)
    assert spec['payload'] == {'merge_method': 'rebase', 'sha': SHA}
    assert spec['delete_branch'] is False


@pytest.mark.parametrize('action, fields, pr_fields, message', [
    ('merge', {'merge_method': 'octopus', 'sha': SHA}, {}, "isn't allowed"),
    ('merge', {'merge_method': 'merge'}, {}, 'out of date'),
    ('merge', {'sha': SHA, 'commit_title': 'x' * 257}, {}, 'at most 256'),
    ('merge', {'sha': SHA}, {'state': 'closed'}, "isn't open"),
    ('close', {}, {'state': 'closed'}, "isn't open"),
    ('reopen', {}, {'state': 'closed', 'merged': True}, "can't be reopened"),
    ('delete', {}, {}, 'Unknown action'),
])
def test_invalid_actions(action, fields, pr_fields, message):
    spec, error = validate_pull_request_action(action, form(**fields), pull(**pr_fields))
    assert spec is None and message in error


def test_disallowed_method_is_rejected():
    pr = pull()
    pr['base']['repo']['allow_rebase_merge'] = False
    assert "isn't allowed" in validate_pull_request_action('merge', form(merge_method='rebase', sha=SHA), pr)[1]


# --- Controller --------------------------------------------------------------

def test_merge_then_delete_branch(github, monkeypatch):
    github['responses'].update({
        ('GET', f'{BASE}/5'): (pull(), None),
        ('PUT', f'{BASE}/5/merge'): ({'merged': True}, None),
    })
    deleted = []
    monkeypatch.setattr(pull_requests_controller, 'delete_branch_ref',
                        lambda owner, repo, branch, token: (deleted.append(branch) or True, None))
    messages, error = apply_pull_request_action('alice', 'app', 5, 'tok', 'merge',
                                                form(merge_method='squash', sha=SHA, delete_branch='on'))
    assert error is None
    assert messages == [('success', 'Pull request merged.'), ('success', 'Branch feature deleted.')]
    assert deleted == ['feature']
    assert ('PUT', f'{BASE}/5/merge', {'merge_method': 'squash', 'sha': SHA}) in github['calls']


def test_branch_delete_failure_is_reported_after_merge(github, monkeypatch):
    github['responses'].update({
        ('GET', f'{BASE}/5'): (pull(), None),
        ('PUT', f'{BASE}/5/merge'): ({'merged': True}, None),
    })
    monkeypatch.setattr(pull_requests_controller, 'delete_branch_ref',
                        lambda *args: (False, 'Reference does not exist'))
    messages, error = apply_pull_request_action('alice', 'app', 5, 'tok', 'merge',
                                                form(sha=SHA, delete_branch='on'))
    assert error is None
    assert messages[1] == ('error', "Merged, but the branch feature couldn't be deleted: Reference does not exist")


def test_merge_conflict_is_reported(github):
    github['responses'].update({
        ('GET', f'{BASE}/5'): (pull(), None),
        ('PUT', f'{BASE}/5/merge'): (None, 'Pull Request is not mergeable'),
    })
    assert apply_pull_request_action('alice', 'app', 5, 'tok', 'merge', form(sha=SHA)) == \
        (None, 'Could not merge: Pull Request is not mergeable')


def test_head_changed_since_page_loaded(github):
    github['responses'].update({
        ('GET', f'{BASE}/5'): (pull(), None),
        ('PUT', f'{BASE}/5/merge'): (None, 'Head branch was modified. Review and try the merge again.'),
    })
    _, error = apply_pull_request_action('alice', 'app', 5, 'tok', 'merge', form(sha='old'))
    assert 'New commits were pushed' in error


def test_close_and_reopen(github):
    github['responses'].update({
        ('GET', f'{BASE}/5'): (pull(), None),
        ('PATCH', f'{BASE}/5'): (pull(state='closed'), None),
    })
    assert apply_pull_request_action('alice', 'app', 5, 'tok', 'close', form()) == \
        ([('success', 'Pull request closed.')], None)
    assert github['calls'][-1] == ('PATCH', f'{BASE}/5', {'state': 'closed'})

    github['responses'][('GET', f'{BASE}/5')] = (pull(state='closed'), None)
    assert apply_pull_request_action('alice', 'app', 5, 'tok', 'reopen', form())[0] == \
        [('success', 'Pull request reopened.')]


def test_invalid_action_makes_no_changes(github):
    github['responses'][('GET', f'{BASE}/5')] = (pull(), None)
    apply_pull_request_action('alice', 'app', 5, 'tok', 'merge', form(merge_method='octopus', sha=SHA))
    assert [call[0] for call in github['calls']] == ['GET']


def test_repo_name_is_url_encoded(github):
    apply_pull_request_action('alice', '../evil', 5, 'tok', 'close', form())
    assert github['calls'][0][1] == '/repos/alice/..%2Fevil/pulls/5'


# --- Routes ------------------------------------------------------------------

def review_responses(github, **pr_fields):
    github['responses'].update({
        ('GET', f'{BASE}/5'): (pull(**pr_fields), None),
        ('GET', f'{BASE}/5/files'): ([{'filename': 'app.py', 'status': 'modified', 'additions': 1, 'deletions': 1,
                                       'patch': '@@ -1 +1 @@\n-old\n+<b>new</b>'}], None),
        ('GET', f'{BASE}/5/reviews'): ([{'user': {'login': 'carol'}, 'state': 'APPROVED', 'body': 'LGTM',
                                         'submitted_at': '2026-11-21T10:00:00Z'}], None),
        ('GET', f'{BASE}/5/comments'): ([{'user': {'login': 'dave'}, 'path': 'app.py', 'line': 1,
                                          'body': 'Nit', 'created_at': '2026-11-21T11:00:00Z'}], None),
        ('GET', f'/repos/alice/app/commits/{SHA}/check-runs'): ({'check_runs': [
            {'name': 'tests', 'status': 'completed', 'conclusion': 'failure', 'html_url': 'https://ci/1'}]}, None),
    })


def test_pull_request_page_shows_diff_reviews_and_checks(logged_in_client, github):
    review_responses(github)
    html = logged_in_client.get('/repositories/app/pull_requests?pr_number=5').data.decode()

    assert 'PR 5' in html and 'Adds a feature' in html
    assert '<span class="add">+&lt;b&gt;new&lt;/b&gt;</span>' in html
    assert 'approved by carol' in html and 'LGTM' in html
    assert 'app.py:1' in html and 'Nit' in html
    assert '1 failing' in html and 'tests' in html
    assert '<option value="squash">Squash and merge</option>' in html
    assert 'name="sha" value="abc123"' in html
    assert 'Delete <code>feature</code> after merging' in html


def test_conflicts_are_shown_and_merge_disabled(logged_in_client, github):
    review_responses(github, mergeable=False, mergeable_state='dirty')
    html = logged_in_client.get('/repositories/app/pull_requests?pr_number=5').data.decode()
    assert 'alert-danger' in html and 'merge conflicts' in html
    assert 'btn btn-success btn-sm" disabled>Merge pull request' in html


def test_closed_pull_request_offers_reopen(logged_in_client, github):
    review_responses(github, state='closed')
    html = logged_in_client.get('/repositories/app/pull_requests?pr_number=5').data.decode()
    assert 'value="reopen"' in html and 'Merge pull request' not in html


def test_page_still_renders_when_review_data_fails(logged_in_client, github):
    github['responses'][('GET', f'{BASE}/5')] = (pull(), None)
    response = logged_in_client.get('/repositories/app/pull_requests?pr_number=5')
    assert response.status_code == 200
    assert b"Couldn&#39;t load files" in response.data


def test_missing_pull_request_is_404(logged_in_client, github):
    assert logged_in_client.get('/repositories/app/pull_requests?pr_number=99').status_code == 404


def test_list_filters_by_state(logged_in_client, github):
    github['responses'][('GET', BASE)] = ([pull(7, state='closed', merged_at='2026-11-22T00:00:00Z')], None)
    html = logged_in_client.get('/repositories/app/pull_requests?state=closed').data.decode()
    assert github['calls'][0][1] == BASE
    assert 'merged' in html and 'pr_number=7' in html


def test_list_post_only_creates(logged_in_client, github):
    response = logged_in_client.post('/repositories/app/pull_requests', data={'action': 'merge', 'pr_number': '5'})
    assert response.status_code == 400


def test_action_route_flashes_each_message(logged_in_client, github, monkeypatch):
    monkeypatch.setattr(pull_request_routes, 'apply_pull_request_action', lambda *args: (
        [('success', 'Pull request merged.'), ('error', 'Merged, but the branch feature couldn\'t be deleted: x')], None))
    response = logged_in_client.post('/repositories/app/pull_requests/5', data={'action': 'merge'})
    assert response.headers['Location'].endswith('/repositories/app/pull_requests?pr_number=5')
    assert [category for category, _ in flashes(logged_in_client)] == ['success', 'error']


def test_action_route_requires_login(client):
    assert client.post('/repositories/app/pull_requests/5', data={'action': 'close'}).status_code == 403
