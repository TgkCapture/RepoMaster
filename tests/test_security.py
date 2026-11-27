"""Tests for the security overview (issue #47). GitHub is never contacted."""
import pytest

from app.controllers import security_controller
from app.controllers.security_controller import (
    get_security_overview, normalize_code, normalize_dependabot, normalize_secret, parse_security_filters,
    severity_counts, unavailable,
)
from app.routes import security_routes

REPOS = [{'full_name': 'alice/app'}, {'full_name': 'alice/site'}]

DEPENDABOT = {
    'number': 4, 'state': 'open', 'html_url': 'https://github.com/alice/app/security/dependabot/4',
    'created_at': '2026-11-01T10:00:00Z',
    'dependency': {'manifest_path': 'requirements.txt'},
    'security_advisory': {'summary': 'ReDoS in <parser>', 'severity': 'high', 'cve_id': 'CVE-2026-1234',
                          'ghsa_id': 'GHSA-xxxx-yyyy-zzzz'},
    'security_vulnerability': {'package': {'ecosystem': 'pip', 'name': 'requests'},
                               'first_patched_version': {'identifier': '2.32.4'}, 'severity': 'high'},
}
SECRET = {
    'number': 2, 'state': 'open', 'html_url': 'https://github.com/alice/app/security/secret-scanning/2',
    'created_at': '2026-11-20T10:00:00Z', 'secret_type': 'aws_access_key_id',
    'secret_type_display_name': 'AWS Access Key ID', 'secret': 'AKIAIOSFODNN7EXAMPLE',
    'validity': 'active', 'publicly_leaked': True,
}
CODE = {
    'number': 7, 'state': 'open', 'html_url': 'https://github.com/alice/site/security/code-scanning/7',
    'created_at': '2026-10-01T10:00:00Z', 'tool': {'name': 'CodeQL'},
    'rule': {'id': 'js/xss', 'description': 'Reflected XSS', 'severity': 'error', 'security_severity_level': 'medium'},
    'most_recent_instance': {'location': {'path': 'src/app.js', 'start_line': 12}},
}


def path(repo, kind):
    return f'/repos/{repo}/{security_controller.KINDS[kind][1]}'


@pytest.fixture
def github(monkeypatch):
    """A fake github_api: path -> (data, error). Unknown paths answer 404."""
    state = {'calls': [], 'responses': {}}

    def fake_api(method, api_path, token, **kwargs):
        assert method == 'GET' and kwargs['params'] == {'state': 'open', 'per_page': 100}
        state['calls'].append(api_path)
        return state['responses'].get(api_path, (None, 'Not Found'))

    monkeypatch.setattr(security_controller, 'github_api', fake_api)
    monkeypatch.setattr(security_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(security_routes, 'get_github_repositories', lambda token: REPOS)
    return state


def all_alerts(github):
    github['responses'].update({
        path('alice/app', 'dependabot'): ([DEPENDABOT], None),
        path('alice/app', 'secret'): ([SECRET], None),
        path('alice/app', 'code'): ([], None),
        path('alice/site', 'dependabot'): (None, 'Dependabot alerts are disabled for this repository.'),
        path('alice/site', 'secret'): (None, 'Resource not accessible by integration'),
        path('alice/site', 'code'): ([CODE], None),
    })


# --- Normalizing -------------------------------------------------------------

def test_normalize_dependabot():
    alert = normalize_dependabot(DEPENDABOT, 'alice/app')
    assert alert['severity'] == 'high' and alert['package'] == 'requests' and alert['ecosystem'] == 'pip'
    assert alert['fix_version'] == '2.32.4' and alert['identifier'] == 'CVE-2026-1234'
    assert alert['location'] == 'requirements.txt' and alert['title'] == 'ReDoS in <parser>'


def test_normalize_dependabot_without_fix_or_cve():
    alert = normalize_dependabot({'number': 1, 'security_advisory': {'severity': 'moderate', 'ghsa_id': 'GHSA-1'},
                                  'security_vulnerability': {'first_patched_version': None}}, 'alice/app')
    assert alert['fix_version'] is None and alert['identifier'] == 'GHSA-1'
    assert alert['severity'] == 'low'  # unknown severities sort last rather than crash


def test_normalize_secret_never_keeps_the_secret():
    alert = normalize_secret(SECRET, 'alice/app')
    assert 'AKIAIOSFODNN7EXAMPLE' not in repr(alert)
    assert alert['severity'] == 'critical' and alert['title'] == 'AWS Access Key ID'
    assert alert['validity'] == 'active' and alert['publicly_leaked'] is True
    assert normalize_secret({**SECRET, 'validity': 'unknown'}, 'alice/app')['validity'] is None


@pytest.mark.parametrize('rule, severity', [
    ({'security_severity_level': 'critical', 'severity': 'error'}, 'critical'),
    ({'severity': 'error'}, 'high'),
    ({'severity': 'warning'}, 'medium'),
    ({'severity': 'note'}, 'low'),
    ({}, 'low'),
])
def test_code_scanning_severity(rule, severity):
    assert normalize_code({'rule': rule}, 'alice/site')['severity'] == severity


def test_normalize_code_location():
    alert = normalize_code(CODE, 'alice/site')
    assert alert['location'] == 'src/app.js:12' and alert['tool'] == 'CodeQL' and alert['title'] == 'Reflected XSS'


# --- Filters -----------------------------------------------------------------

def test_parse_filters():
    filters, warnings = parse_security_filters({'severity': 'high', 'kind': 'code', 'repo': 'alice/app'}, {'alice/app'})
    assert filters == {'severity': 'high', 'kind': 'code', 'repo': 'alice/app'} and warnings == []
    filters, warnings = parse_security_filters({'severity': 'urgent', 'kind': 'x', 'repo': 'mallory/app'}, {'alice/app'})
    assert filters == {'severity': '', 'kind': '', 'repo': ''} and len(warnings) == 3


# --- Fetching ----------------------------------------------------------------

def test_overview_sorts_by_severity_and_records_coverage(github):
    all_alerts(github)
    overview = get_security_overview(['alice/app', 'alice/site'], list(security_controller.KINDS), 'tok')
    assert [(a['kind'], a['severity']) for a in overview['alerts']] == [
        ('secret', 'critical'), ('dependabot', 'high'), ('code', 'medium')]
    assert overview['coverage']['alice/site']['dependabot'] == {
        'count': 0, 'truncated': False, 'error': 'Dependabot alerts are disabled for this repository.'}
    assert overview['coverage']['alice/app']['code'] == {'count': 0, 'truncated': False, 'error': None}
    assert severity_counts(overview['alerts']) == {'critical': 1, 'high': 1, 'medium': 1, 'low': 0}


def test_unavailable_groups_by_reason(github):
    all_alerts(github)
    github['responses'][path('alice/app', 'secret')] = (None, 'Resource not accessible by integration')
    coverage = get_security_overview(['alice/app', 'alice/site'], list(security_controller.KINDS), 'tok')['coverage']
    assert unavailable(coverage) == [
        ('Resource not accessible by integration', [('alice/app', 'Secret scanning'), ('alice/site', 'Secret scanning')]),
        ('Dependabot alerts are disabled for this repository.', [('alice/site', 'Dependabot')]),
    ]


def test_full_page_is_reported_as_truncated(github):
    github['responses'][path('alice/app', 'code')] = ([{**CODE, 'number': n} for n in range(100)], None)
    overview = get_security_overview(['alice/app'], ['code'], 'tok')
    assert overview['coverage']['alice/app']['code']['truncated'] is True


def test_unexpected_response_is_an_error(github):
    github['responses'][path('alice/app', 'code')] = ({'message': 'odd'}, None)
    overview = get_security_overview(['alice/app'], ['code'], 'tok')
    assert overview['alerts'] == [] and overview['coverage']['alice/app']['code']['error']


def test_names_are_quoted_in_paths(github):
    get_security_overview(['alice/my app'], ['secret'], 'tok')
    assert github['calls'] == ['/repos/alice/my%20app/secret-scanning/alerts']


# --- Page --------------------------------------------------------------------

def test_page_lists_alerts_with_details(logged_in_client, github):
    all_alerts(github)
    html = logged_in_client.get('/security').data.decode()
    assert 'ReDoS in &lt;parser&gt;' in html and 'fixed in <strong>2.32.4</strong>' in html
    assert 'AWS Access Key ID' in html and 'still active' in html and 'leaked publicly' in html
    assert 'AKIAIOSFODNN7EXAMPLE' not in html
    assert 'src/app.js:12' in html and 'CodeQL' in html
    assert 'href="https://github.com/alice/app/security/dependabot/4"' in html
    # Most severe first
    assert html.index('AWS Access Key ID') < html.index('ReDoS') < html.index('Reflected XSS')
    assert "Couldn't check 2 repository" in html and 'Dependabot alerts are disabled' in html


def test_severity_filter_keeps_counts(logged_in_client, github):
    all_alerts(github)
    html = logged_in_client.get('/security?severity=high').data.decode()
    assert 'ReDoS' in html and 'AWS Access Key ID' not in html and 'Reflected XSS' not in html
    assert '>All <span class="badge bg-light text-dark">3</span>' in html


def test_repo_and_kind_filters_limit_github_calls(logged_in_client, github):
    all_alerts(github)
    html = logged_in_client.get('/security?repo=alice/site&kind=code').data.decode()
    assert github['calls'] == [path('alice/site', 'code')]
    assert 'Reflected XSS' in html and 'ReDoS' not in html
    # Severity links keep the other filters
    assert '/security?severity=critical&amp;kind=code&amp;repo=alice/site' in html


def test_unknown_repo_is_ignored_not_fetched(logged_in_client, github):
    html = logged_in_client.get('/security?repo=mallory/secrets').data.decode()
    assert 'Ignored unknown repo' in html
    assert not any('mallory' in call for call in github['calls'])


def test_no_alerts_message(logged_in_client, github):
    for repo in ('alice/app', 'alice/site'):
        for kind in security_controller.KINDS:
            github['responses'][path(repo, kind)] = ([], None)
    html = logged_in_client.get('/security').data.decode()
    assert 'No open alerts' in html and "Couldn" not in html


def test_truncation_warning(logged_in_client, github):
    github['responses'][path('alice/app', 'dependabot')] = ([{**DEPENDABOT, 'number': n} for n in range(100)], None)
    html = logged_in_client.get('/security?repo=alice/app&kind=dependabot').data.decode()
    assert 'Only the first 100 alerts' in html and 'alice/app (Dependabot)' in html


def test_token_and_repository_failures(logged_in_client, monkeypatch):
    monkeypatch.setattr(security_routes, 'get_installation_access_token', lambda: None)
    assert logged_in_client.get('/security').status_code == 500
    monkeypatch.setattr(security_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(security_routes, 'get_github_repositories', lambda token: None)
    assert logged_in_client.get('/security').status_code == 500


def test_requires_login(client):
    assert client.get('/security').status_code == 403


def test_linked_from_repositories_page(logged_in_client, monkeypatch):
    from app.routes import repo_routes
    monkeypatch.setattr(repo_routes, 'get_installation_access_token', lambda: 'tok')
    monkeypatch.setattr(repo_routes, 'get_github_repositories', lambda token: [])
    assert 'href="/security"' in logged_in_client.get('/github/repositories').data.decode()
