"""Tests for full issue management (issue #39). GitHub is never contacted."""
import pytest
from werkzeug.datastructures import MultiDict

from app.controllers import issues_controller
from app.controllers.issues_controller import (
    apply_issue_action, list_issues, parse_issue_number, parse_state, validate_issue_action,
)
from app.routes import issue_routes

BASE = '/repos/alice/app/issues'
MILESTONES = [{'number': 1, 'title': 'v1.0'}, {'number': 2, 'title': 'v2.0'}]


def issue(number=7, **fields):
    data = {
        'number': number, 'title': f'Issue {number}', 'body': 'Steps to reproduce', 'state': 'open',
        'html_url': f'https://github.com/alice/app/issues/{number}', 'user': {'login': 'bob'},
        'created_at': '2026-11-20T10:00:00Z', 'labels': [], 'assignees': [], 'milestone': None, 'comments': 0,
    }
    data.update(fields)
    return data


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: responses are looked up by (method, path); every call is recorded."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append((method, path, kwargs.get('json'), kwargs.get('params')))
        return state['responses'].get((method, path), (None, 'Not Found'))

    monkeypatch.setattr(issues_controller, 'github_api', fake_api)
    monkeypatch.setattr(issue_routes, 'get_installation_access_token', lambda: 'tok')
    return state


def form(**fields):
    return MultiDict(fields)


# --- Parsing and validation --------------------------------------------------

def test_parse_state_defaults_to_open():
    assert [parse_state(v) for v in ('open', 'closed', 'all', 'bogus', None)] == \
        ['open', 'closed', 'all', 'open', 'open']


@pytest.mark.parametrize('value, expected', [('7', 7), ('0', None), ('-1', None), ('x', None), (None, None)])
def test_parse_issue_number(value, expected):
    assert parse_issue_number(value) == expected


def test_edit_strips_title_and_keeps_body():
    spec, error = validate_issue_action('edit', form(title='  New title ', body='Line 1\nLine 2'))
    assert error is None
    assert spec == ('PATCH', '', {'title': 'New title', 'body': 'Line 1\nLine 2'})


@pytest.mark.parametrize('fields, message', [
    ({'title': '   '}, "can't be empty"),
    ({'title': 'x' * 257}, 'at most 256'),
    ({'title': 'ok', 'body': 'x' * 65537}, 'at most 65536'),
])
def test_edit_rejects_bad_input(fields, message):
    spec, error = validate_issue_action('edit', form(**fields))
    assert spec is None and message in error


def test_close_uses_reason_and_reopen_sets_open():
    assert validate_issue_action('close', form())[0] == \
        ('PATCH', '', {'state': 'closed', 'state_reason': 'completed'})
    assert validate_issue_action('close', form(state_reason='not_planned'))[0][2]['state_reason'] == 'not_planned'
    assert validate_issue_action('close', form(state_reason='reopened'))[1] == "Unknown close reason."
    assert validate_issue_action('reopen', form())[0] == ('PATCH', '', {'state': 'open'})


def test_comment_requires_text():
    assert validate_issue_action('comment', form(body=' \n '))[1] == "The comment can't be empty."
    assert validate_issue_action('comment', form(body='Thanks!'))[0] == ('POST', '/comments', {'body': 'Thanks!'})


def test_labels_are_url_encoded_when_removed():
    assert validate_issue_action('add_label', form(label='good first issue'))[0] == \
        ('POST', '/labels', {'labels': ['good first issue']})
    assert validate_issue_action('remove_label', form(label='needs/triage ?'))[0] == \
        ('DELETE', '/labels/needs%2Ftriage%20%3F', None)
    assert validate_issue_action('add_label', form(label=''))[1] == "Choose a label."
    assert validate_issue_action('add_label', form(label='x' * 51))[1] == "Choose a label."


def test_assignees_must_be_valid_logins():
    assert validate_issue_action('add_assignee', form(assignee='@carol'))[0] == \
        ('POST', '/assignees', {'assignees': ['carol']})
    assert validate_issue_action('remove_assignee', form(assignee='carol'))[0] == \
        ('DELETE', '/assignees', {'assignees': ['carol']})
    for bad in ('', 'bad name', '../x', '-carol'):
        assert validate_issue_action('add_assignee', form(assignee=bad))[1] == "Choose a valid GitHub username."


def test_milestone_set_and_clear():
    options = {'milestones': MILESTONES}
    assert validate_issue_action('set_milestone', form(milestone='2'), options)[0] == ('PATCH', '', {'milestone': 2})
    assert validate_issue_action('set_milestone', form(milestone=''), options)[0] == ('PATCH', '', {'milestone': None})
    assert validate_issue_action('set_milestone', form(milestone='9'), options)[1] == \
        "That milestone doesn't exist or is closed."
    assert validate_issue_action('set_milestone', form(milestone='abc'), options)[1] == "Choose a milestone."


def test_unknown_action_is_rejected():
    assert validate_issue_action('delete', form()) == (None, "Unknown action.")
    assert validate_issue_action(None, form()) == (None, "Unknown action.")


# --- Controller --------------------------------------------------------------

def test_list_issues_leaves_out_pull_requests(github):
    github['responses'][('GET', BASE)] = ([issue(1), issue(2, pull_request={'url': '...'})], None)
    issues, error = list_issues('alice', 'app', 'tok', state='closed')
    assert error is None
    assert [i['number'] for i in issues] == [1]
    assert github['calls'][0][3] == {'state': 'closed', 'per_page': 100}


def test_list_issues_ignores_unknown_state(github):
    github['responses'][('GET', BASE)] = ([], None)
    list_issues('alice', 'app', 'tok', state='; drop')
    assert github['calls'][0][3]['state'] == 'open'


def test_owner_and_repo_are_url_encoded(github):
    list_issues('alice', '../evil', 'tok')
    assert github['calls'][0][1] == '/repos/alice/..%2Fevil/issues'


def test_apply_action_posts_to_github(github):
    github['responses'][('POST', f'{BASE}/7/comments')] = ({'id': 1}, None)
    assert apply_issue_action('alice', 'app', 7, 'tok', 'comment', form(body='Hi')) == ("Comment posted.", None)
    assert github['calls'] == [('POST', f'{BASE}/7/comments', {'body': 'Hi'}, None)]


def test_apply_action_reports_github_errors(github):
    github['responses'][('PATCH', f'{BASE}/7')] = (None, 'Validation Failed')
    assert apply_issue_action('alice', 'app', 7, 'tok', 'reopen', form()) == (None, 'Validation Failed')


def test_apply_action_does_not_call_github_when_invalid(github):
    assert apply_issue_action('alice', 'app', 7, 'tok', 'comment', form(body='')) == \
        (None, "The comment can't be empty.")
    assert github['calls'] == []


def test_remove_label_sends_no_body(github):
    github['responses'][('DELETE', f'{BASE}/7/labels/bug')] = ([], None)
    assert apply_issue_action('alice', 'app', 7, 'tok', 'remove_label', form(label='bug'))[0] == "Label removed."
    assert github['calls'][0] == ('DELETE', f'{BASE}/7/labels/bug', None, None)


def test_assigning_someone_github_skipped_is_an_error(github):
    # GitHub returns 201 but leaves out users who can't be assigned.
    github['responses'][('POST', f'{BASE}/7/assignees')] = (issue(assignees=[]), None)
    message, error = apply_issue_action('alice', 'app', 7, 'tok', 'add_assignee', form(assignee='mallory'))
    assert message is None and "mallory can't be assigned" in error

    github['responses'][('POST', f'{BASE}/7/assignees')] = (issue(assignees=[{'login': 'Carol'}]), None)
    assert apply_issue_action('alice', 'app', 7, 'tok', 'add_assignee', form(assignee='carol')) == \
        ("Assignee added.", None)


# --- Routes ------------------------------------------------------------------

def test_issue_list_filters_by_state_and_links_to_detail(logged_in_client, github):
    github['responses'][('GET', BASE)] = ([issue(3, state='closed', labels=[{'name': 'bug', 'color': 'd73a4a'}])], None)
    html = logged_in_client.get('/repositories/app/issues?state=closed').data.decode()

    assert github['calls'][0][3]['state'] == 'closed'
    assert 'href="/repositories/app/issues/3"' in html
    assert 'value="reopen"' in html and 'value="close"' not in html
    assert 'background-color: #d73a4a' in html


def test_issue_list_failure_returns_500(logged_in_client, github):
    response = logged_in_client.get('/repositories/app/issues')
    assert response.status_code == 500


def test_legacy_issue_number_link_redirects_to_detail(logged_in_client, github):
    response = logged_in_client.get('/repositories/app/issues?issue_number=7')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/repositories/app/issues/7')
    assert github['calls'] == []


def test_reopen_from_list_redirects_back_with_state(logged_in_client, github):
    github['responses'][('PATCH', f'{BASE}/3')] = (issue(3), None)
    response = logged_in_client.post('/repositories/app/issues',
                                     data={'action': 'reopen', 'issue_number': '3', 'state': 'closed'})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/repositories/app/issues?state=closed')
    assert github['calls'] == [('PATCH', f'{BASE}/3', {'state': 'open'}, None)]


def test_close_from_list_requires_issue_number(logged_in_client, github):
    response = logged_in_client.post('/repositories/app/issues', data={'action': 'close'})
    assert response.status_code == 400


def test_creating_an_issue_opens_its_page(logged_in_client, github, monkeypatch):
    monkeypatch.setattr(issue_routes, 'create_github_issue', lambda repo, title, body: {'number': 12})
    response = logged_in_client.post('/repositories/app/issues', data={'title': 'Bug', 'body': ''})
    assert response.headers['Location'].endswith('/repositories/app/issues/12')


def test_issue_detail_shows_comments_and_pickers(logged_in_client, github):
    github['responses'].update({
        ('GET', f'{BASE}/7'): (issue(labels=[{'name': 'bug', 'color': 'd73a4a'}],
                                     assignees=[{'login': 'carol'}], milestone=MILESTONES[1]), None),
        ('GET', f'{BASE}/7/comments'): ([{'user': {'login': 'dave'}, 'body': '<script>x</script>',
                                          'created_at': '2026-11-21T10:00:00Z'}], None),
        ('GET', '/repos/alice/app/labels'): ([{'name': 'bug', 'color': 'd73a4a'}, {'name': 'docs', 'color': '0075ca'}], None),
        ('GET', '/repos/alice/app/assignees'): ([{'login': 'carol'}, {'login': 'erin'}], None),
        ('GET', '/repos/alice/app/milestones'): (MILESTONES, None),
    })
    html = logged_in_client.get('/repositories/app/issues/7').data.decode()

    assert 'Issue 7' in html and 'Steps to reproduce' in html
    assert 'Comments (1)' in html and 'dave' in html
    assert '&lt;script&gt;x&lt;/script&gt;' in html and '<script>x</script>' not in html
    # Pickers only offer labels/assignees the issue doesn't have yet
    assert '<option value="docs">' in html and '<option value="bug">' not in html
    assert '<option value="erin">' in html and '<option value="carol">' not in html
    assert '<option value="2" selected>v2.0</option>' in html


def test_issue_detail_still_works_when_options_fail(logged_in_client, github):
    github['responses'][('GET', f'{BASE}/7')] = (issue(), None)
    github['responses'][('GET', f'{BASE}/7/comments')] = ([], None)
    response = logged_in_client.get('/repositories/app/issues/7')
    assert response.status_code == 200
    assert b'No comments yet.' in response.data


def test_closed_milestone_is_shown_as_current(logged_in_client, github):
    github['responses'][('GET', f'{BASE}/7')] = (issue(milestone={'number': 5, 'title': 'Old'}), None)
    github['responses'][('GET', f'{BASE}/7/comments')] = ([], None)
    html = logged_in_client.get('/repositories/app/issues/7').data.decode()
    assert 'Old (closed)' in html


def test_issue_detail_not_found(logged_in_client, github):
    assert logged_in_client.get('/repositories/app/issues/99').status_code == 404


def test_pull_request_number_redirects_to_pull_request_page(logged_in_client, github):
    github['responses'][('GET', f'{BASE}/8')] = (issue(8, pull_request={'url': '...'}), None)
    response = logged_in_client.get('/repositories/app/issues/8')
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/repositories/app/pull_requests?pr_number=8')


def test_action_flashes_result_and_redirects(logged_in_client, github):
    github['responses'][('POST', f'{BASE}/7/labels')] = ([{'name': 'docs'}], None)
    response = logged_in_client.post('/repositories/app/issues/7', data={'action': 'add_label', 'label': 'docs'})
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/repositories/app/issues/7')
    with logged_in_client.session_transaction() as sess:
        assert sess['_flashes'] == [('success', 'Label added.')]


def test_action_error_is_flashed(logged_in_client, github):
    logged_in_client.post('/repositories/app/issues/7', data={'action': 'comment', 'body': ''})
    with logged_in_client.session_transaction() as sess:
        assert sess['_flashes'] == [('error', "The comment can't be empty.")]
    assert github['calls'] == []


def test_set_milestone_checks_the_repository_milestones(logged_in_client, github):
    github['responses'][('GET', '/repos/alice/app/milestones')] = (MILESTONES, None)
    logged_in_client.post('/repositories/app/issues/7', data={'action': 'set_milestone', 'milestone': '9'})
    with logged_in_client.session_transaction() as sess:
        assert sess['_flashes'] == [('error', "That milestone doesn't exist or is closed.")]
    assert not any(call[0] == 'PATCH' for call in github['calls'])


def test_actions_require_login(client):
    response = client.post('/repositories/app/issues/7', data={'action': 'reopen'})
    assert response.status_code == 403
