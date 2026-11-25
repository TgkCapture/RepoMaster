"""Tests for the repository analytics page (issue #44). GitHub is never contacted."""
import json
import re
import pytest

from app.controllers import analytics_controller
from app.controllers.analytics_controller import (
    COMPUTING, fetch_stats, get_analytics, summarize_commit_activity, summarize_contributors,
    summarize_languages, summarize_traffic,
)
from app.routes import analytics_routes

BASE = '/repos/alice/app'
VIEWS = {'count': 30, 'uniques': 7, 'views': [
    {'timestamp': '2026-11-20T00:00:00Z', 'count': 10, 'uniques': 3},
    {'timestamp': '2026-11-21T00:00:00Z', 'count': 20, 'uniques': 5}]}
CLONES = {'count': 4, 'uniques': 2, 'clones': [{'timestamp': '2026-11-21T00:00:00Z', 'count': 4, 'uniques': 2}]}
ACTIVITY = [{'week': 1763856000, 'total': 3, 'days': [0] * 7}, {'week': 1764460800, 'total': 5, 'days': [0] * 7}]
CONTRIBUTORS = [
    {'author': {'login': 'bob', 'html_url': 'https://github.com/bob'}, 'total': 4,
     'weeks': [{'a': 10, 'd': 2, 'c': 4}]},
    {'author': {'login': 'alice', 'html_url': 'https://github.com/alice'}, 'total': 9,
     'weeks': [{'a': 100, 'd': 5, 'c': 6}, {'a': 1, 'd': 1, 'c': 3}]},
    {'author': None, 'total': 1, 'weeks': []},
]


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: path -> list of responses (the last one repeats)."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, path, token, **kwargs):
        state['calls'].append(path)
        queue = state['responses'].get(path, [(None, 'Not Found')])
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(analytics_controller, 'github_api', fake_api)
    monkeypatch.setattr(analytics_routes, 'get_installation_access_token', lambda: 'tok')
    return state


def all_sections(github):
    github['responses'].update({
        f'{BASE}/traffic/views': [(VIEWS, None)],
        f'{BASE}/traffic/clones': [(CLONES, None)],
        f'{BASE}/traffic/popular/referrers': [([{'referrer': 'google.com', 'count': 5, 'uniques': 2}], None)],
        f'{BASE}/traffic/popular/paths': [([{'path': '/alice/app', 'title': '<app>', 'count': 9, 'uniques': 4}], None)],
        f'{BASE}/languages': [({'Python': 750, 'HTML': 250}, None)],
        f'{BASE}/stats/commit_activity': [(ACTIVITY, None)],
        f'{BASE}/stats/contributors': [(CONTRIBUTORS, None)],
    })


# --- Summaries ---------------------------------------------------------------

def test_summarize_traffic():
    assert summarize_traffic(VIEWS) == {'count': 30, 'uniques': 7, 'days': ['2026-11-20', '2026-11-21'],
                                        'totals': [10, 20], 'unique_totals': [3, 5]}
    assert summarize_traffic(CLONES)['days'] == ['2026-11-21']
    assert summarize_traffic(None)['count'] == 0


def test_summarize_commit_activity():
    assert summarize_commit_activity(ACTIVITY) == {'weeks': ['2025-11-23', '2025-11-30'], 'totals': [3, 5], 'total': 8}


def test_summarize_contributors_sorts_and_sums():
    rows = summarize_contributors(CONTRIBUTORS)
    assert [r['login'] for r in rows] == ['alice', 'bob', 'unknown']
    assert rows[0] == {'login': 'alice', 'html_url': 'https://github.com/alice', 'commits': 9,
                       'additions': 101, 'deletions': 6}


def test_summarize_contributors_keeps_top_20():
    many = [{'author': {'login': f'u{i}'}, 'total': i, 'weeks': []} for i in range(30)]
    rows = summarize_contributors(many)
    assert len(rows) == 20 and rows[0]['commits'] == 29


def test_summarize_languages():
    assert summarize_languages({'HTML': 250, 'Python': 750}) == [
        {'name': 'Python', 'bytes': 750, 'percent': 75.0}, {'name': 'HTML', 'bytes': 250, 'percent': 25.0}]
    assert summarize_languages({}) == []


# --- Stats retries -----------------------------------------------------------

def test_stats_retry_while_github_computes(github):
    waits = []
    github['responses']['/stats'] = [({}, None), ({}, None), (ACTIVITY, None)]
    assert fetch_stats('/stats', 'tok', sleep=waits.append) == (ACTIVITY, None)
    assert waits == [2, 4]


def test_stats_give_up_after_three_tries(github):
    waits = []
    github['responses']['/stats'] = [({}, None)]
    assert fetch_stats('/stats', 'tok', sleep=waits.append) == (None, COMPUTING)
    assert len(github['calls']) == 3 and waits == [2, 4]


def test_stats_empty_repository_and_errors(github):
    github['responses']['/stats'] = [(None, None)]
    assert fetch_stats('/stats', 'tok', sleep=lambda s: None) == ([], None)
    github['responses']['/stats'] = [(None, 'Forbidden')]
    assert fetch_stats('/stats', 'tok', sleep=lambda s: None) == (None, 'Forbidden')


def test_each_section_fails_independently(github):
    all_sections(github)
    github['responses'][f'{BASE}/traffic/views'] = [(None, 'Resource not accessible by integration')]
    sections = get_analytics('alice', 'app', 'tok', sleep=lambda s: None)
    assert sections['views'] == {'data': None, 'error': 'Resource not accessible by integration'}
    assert sections['clones']['data']['count'] == 4
    assert sections['languages']['data'][0]['name'] == 'Python'
    assert len(github['calls']) == 7


# --- Route -------------------------------------------------------------------

def test_analytics_page(logged_in_client, github, monkeypatch):
    all_sections(github)
    html = logged_in_client.get('/repos/alice/app/analytics').data.decode()

    assert '>30</div>' in html and '>7</div>' in html and '>4</div>' in html and '>8</div>' in html
    assert 'id="chart-views"' in html and 'id="chart-commit_activity"' in html and 'id="chart-languages"' in html
    assert 'google.com' in html and '&lt;app&gt;' in html
    assert 'https://github.com/alice' in html and '101' in html

    data = json.loads(re.search(r'<script type="application/json" id="analytics-data">(.*?)</script>', html, re.S).group(1))
    assert data['views']['totals'] == [10, 20]
    assert data['languages'][0] == {'name': 'Python', 'bytes': 750, 'percent': 75.0}


def test_chart_data_cannot_break_out_of_script(logged_in_client, github):
    all_sections(github)
    github['responses'][f'{BASE}/languages'] = [({'</script><script>alert(1)</script>': 10}, None)]
    html = logged_in_client.get('/repos/alice/app/analytics').data.decode()
    assert '</script><script>alert(1)' not in html


def test_errors_and_empty_sections_are_explained(logged_in_client, github, monkeypatch):
    all_sections(github)
    github['responses'][f'{BASE}/traffic/views'] = [(None, 'Resource not accessible by integration')]
    github['responses'][f'{BASE}/stats/contributors'] = [({}, None)]
    github['responses'][f'{BASE}/languages'] = [({}, None)]
    monkeypatch.setattr(analytics_controller, 'STATS_RETRY_SECONDS', 0)
    html = logged_in_client.get('/repos/alice/app/analytics').data.decode()
    assert "Couldn't load this: Resource not accessible by integration" in html
    assert 'still computing' in html
    assert 'No code detected.' in html
    assert 'id="chart-views"' not in html


def test_invalid_repository_name(logged_in_client, github):
    assert logged_in_client.get('/repos/alice/bad%20name/analytics').status_code == 400
    assert github['calls'] == []


def test_requires_login(client):
    assert client.get('/repos/alice/app/analytics').status_code == 403
