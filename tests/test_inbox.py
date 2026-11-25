"""Tests for the cross-repository issue & PR inbox (issue #37). GitHub is never contacted."""
from datetime import datetime, timezone
import pytest
from werkzeug.datastructures import MultiDict

from app.controllers import auth_controller
from app.controllers.inbox_controller import (
    build_search_query, label_text_color, parse_inbox_filters, time_ago, to_inbox_items,
)
from app.routes import inbox_routes

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)
REPOS = {'alice/app', 'alice/lib'}


def filters_from(**args):
    filters, warnings = parse_inbox_filters(MultiDict(args), REPOS)
    return filters, warnings


def search_item(repo='alice/app', number=1, pr=False, **fields):
    item = {
        'repository_url': f'https://api.github.com/repos/{repo}',
        'number': number, 'title': f'Item {number}', 'html_url': f'https://github.com/{repo}/issues/{number}',
        'user': {'login': 'bob'}, 'labels': [], 'comments': 0,
        'created_at': '2026-10-30T12:00:00Z', 'updated_at': '2026-11-01T11:00:00Z',
    }
    if pr:
        item['pull_request'] = {'url': '...'}
    item.update(fields)
    return item


# --- Filters -----------------------------------------------------------------

def test_default_filters():
    filters, warnings = filters_from()
    assert filters == {'type': '', 'age': '', 'sort': 'updated', 'repo': '', 'label': '', 'author': '', 'page': 1}
    assert warnings == []


def test_valid_filters_are_kept():
    filters, warnings = filters_from(type='pr', age='old90', sort='oldest', repo='alice/lib',
                                     label='good first issue', author='@dependabot[bot]', page='3')
    assert filters == {'type': 'pr', 'age': 'old90', 'sort': 'oldest', 'repo': 'alice/lib',
                       'label': 'good first issue', 'author': 'dependabot[bot]', 'page': 3}
    assert warnings == []


@pytest.mark.parametrize('args, field, warning', [
    ({'type': 'commit'}, 'type', "unknown type"),
    ({'sort': 'random'}, 'sort', "unknown sort"),
    ({'repo': 'mallory/secret'}, 'repo', "not available"),
    ({'label': 'bug" OR is:closed'}, 'label', "quotes"),
    ({'author': 'bob is:closed'}, 'author', "not a valid GitHub username"),
])
def test_invalid_filters_are_dropped_with_a_warning(args, field, warning):
    filters, warnings = filters_from(**args)
    assert filters[field] == ('updated' if field == 'sort' else '')
    assert warning in warnings[0]


@pytest.mark.parametrize('page, expected', [('0', 1), ('-2', 1), ('abc', 1), ('500', 20)])
def test_page_is_clamped_to_search_limits(page, expected):
    assert filters_from(page=page)[0]['page'] == expected


# --- Query building ----------------------------------------------------------

def test_query_for_user_account():
    filters, _ = filters_from()
    assert build_search_query('alice', 'User', filters, NOW) == 'is:open user:alice'


def test_query_for_organization_account():
    filters, _ = filters_from()
    assert build_search_query('acme', 'Organization', filters, NOW) == 'is:open org:acme'


def test_query_defaults_to_user_when_account_type_unknown():
    filters, _ = filters_from()
    assert build_search_query('alice', None, filters, NOW) == 'is:open user:alice'


def test_query_with_all_filters():
    filters, _ = filters_from(type='issue', repo='alice/lib', label='good first issue',
                              author='bob', age='old30')
    assert build_search_query('alice', 'User', filters, NOW) == (
        'is:open repo:alice/lib is:issue label:"good first issue" author:bob created:<2026-10-02')


def test_query_for_recent_pull_requests():
    filters, _ = filters_from(type='pr', age='new7')
    assert build_search_query('alice', 'User', filters, NOW) == 'is:open user:alice is:pr created:>=2026-10-25'


# --- Result conversion -------------------------------------------------------

@pytest.mark.parametrize('seconds_ago, expected', [
    (5, 'just now'), (60, '1 minute ago'), (7200, '2 hours ago'),
    (86400 * 3, '3 days ago'), (86400 * 45, '1 month ago'), (86400 * 800, '2 years ago'),
])
def test_time_ago(seconds_ago, expected):
    from datetime import timedelta
    assert time_ago(NOW - timedelta(seconds=seconds_ago), NOW) == expected


def test_time_ago_unknown():
    assert time_ago(None) == 'unknown'


def test_to_inbox_items_converts_and_filters():
    results = [
        search_item('alice/app', 1, labels=[{'name': 'bug', 'color': 'd73a4a'}, {'name': 'x', 'color': 'red;}'}]),
        search_item('alice/lib', 2, pr=True, draft=True, comments=3),
        search_item('alice/not-installed', 3),
    ]

    items, hidden = to_inbox_items(results, REPOS, NOW)

    assert hidden == 1
    issue, pr = items
    assert (issue['kind'], issue['repo'], issue['repo_name'], issue['number']) == ('issue', 'alice/app', 'app', 1)
    assert issue['labels'] == [{'name': 'bug', 'color': 'd73a4a'}, {'name': 'x', 'color': 'cccccc'}]
    assert issue['created_ago'] == '2 days ago'
    assert issue['updated_ago'] == '1 hour ago'
    assert (pr['kind'], pr['draft'], pr['comments'], pr['author']) == ('pr', True, 3, 'bob')


def test_label_text_color():
    assert label_text_color('ffffff') == '#000000'
    assert label_text_color('000000') == '#ffffff'


def test_sign_in_stores_account_type(app):
    with app.test_request_context():
        auth_controller.start_user_session(
            {'login': 'alice'}, {'id': 9, 'account': {'login': 'acme', 'type': 'Organization'}})
        from flask import session
        assert session['github_account_type'] == 'Organization'


# --- Route -------------------------------------------------------------------

def test_inbox_requires_login(client):
    assert client.get('/inbox').status_code == 403


@pytest.fixture
def github(monkeypatch):
    state = {'queries': [], 'response': ({'total_count': 2, 'items': [
        search_item('alice/app', 1, labels=[{'name': 'bug', 'color': 'd73a4a'}]),
        search_item('alice/app', 2, pr=True),
    ]}, None)}

    def fake_search(query, token, sort, order, page, per_page):
        state['queries'].append({'query': query, 'sort': sort, 'order': order, 'page': page})
        return state['response']

    monkeypatch.setattr(inbox_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(inbox_routes, 'get_github_repositories', lambda token: [
        {'full_name': 'alice/app'}, {'full_name': 'alice/lib'}])
    monkeypatch.setattr(inbox_routes, 'search_issues', fake_search)
    return state


def test_inbox_lists_issues_and_prs_with_in_app_links(logged_in_client, github):
    html = logged_in_client.get('/inbox').data.decode()

    assert github['queries'] == [{'query': 'is:open user:alice', 'sort': 'updated', 'order': 'desc', 'page': 1}]
    assert '2 results' in html
    assert 'Item 1' in html and 'Item 2' in html
    assert 'href="/repositories/app/issues/1"' in html
    assert 'href="/repositories/app/pull_requests?pr_number=2"' in html
    assert 'background-color: #d73a4a' in html
    assert '<option value="alice/lib" >alice/lib</option>' in html  # repo filter option


def test_inbox_applies_filters_and_sort(logged_in_client, github):
    logged_in_client.get('/inbox?type=pr&repo=alice/lib&sort=oldest&author=bob')
    query = github['queries'][0]
    assert query['query'] == 'is:open repo:alice/lib is:pr author:bob'
    assert (query['sort'], query['order']) == ('created', 'asc')


def test_inbox_shows_warning_for_ignored_filter(logged_in_client, github):
    html = logged_in_client.get('/inbox?repo=mallory/secret').data.decode()
    assert 'not available to this installation' in html
    assert github['queries'][0]['query'] == 'is:open user:alice'


def test_inbox_pagination_keeps_filters(logged_in_client, github):
    github['response'] = ({'total_count': 120, 'items': []}, None)

    html = logged_in_client.get('/inbox?type=issue&page=2').data.decode()

    assert 'page=1' in html and 'page=3' in html
    assert 'type=issue' in html
    assert github['queries'][0]['page'] == 2


def test_inbox_shows_search_errors(logged_in_client, github):
    github['response'] = (None, 'API rate limit exceeded')
    response = logged_in_client.get('/inbox')
    assert response.status_code == 200
    assert b'Could not search GitHub: API rate limit exceeded' in response.data
