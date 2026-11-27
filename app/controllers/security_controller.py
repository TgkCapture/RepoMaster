"""security_controller.py

Security overview across repositories (issue #47): open Dependabot, secret scanning and
code scanning alerts for every repository the installation can access.

Each (repository, alert kind) is fetched on its own, so a feature that is disabled or a
permission the App lacks only marks that cell as unavailable instead of failing the page.
The secret value GitHub returns with secret scanning alerts is never kept.
"""
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
from app.controllers.repo_controller import github_api
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago

PER_REPO = 100  # one page per repository and kind; more than this is reported as truncated
MAX_WORKERS = 8

KINDS = {
    'dependabot': ('Dependabot', 'dependabot/alerts'),
    'secret': ('Secret scanning', 'secret-scanning/alerts'),
    'code': ('Code scanning', 'code-scanning/alerts'),
}

# Most severe first; the order is used for sorting
SEVERITIES = ('critical', 'high', 'medium', 'low')

# Code scanning rules that aren't security rules only have error / warning / note
CODE_SEVERITY = {'error': 'high', 'warning': 'medium', 'note': 'low'}

# GitHub doesn't rate leaked secrets; any exposed credential is treated as critical
SECRET_SEVERITY = 'critical'


def parse_security_filters(args, repo_full_names):
    """Read severity / kind / repo filters. Unknown values are dropped and reported. Returns (filters, warnings)."""
    warnings = []

    def choice(key, options):
        value = (args.get(key) or '').strip()
        if value and value not in options:
            warnings.append(f"Ignored unknown {key} '{value}'.")
            return ''
        return value

    return {
        'severity': choice('severity', SEVERITIES),
        'kind': choice('kind', KINDS),
        'repo': choice('repo', repo_full_names),
    }, warnings


def _severity(value):
    value = (value or '').lower()
    return value if value in SEVERITIES else 'low'


def _base(alert, kind, repo):
    created = parse_github_date(alert.get('created_at'))
    return {
        'kind': kind,
        'repo': repo,
        'number': alert.get('number'),
        'html_url': alert.get('html_url'),
        'created_at': created,
        'created_ago': time_ago(created),
    }


def normalize_dependabot(alert, repo):
    advisory = alert.get('security_advisory') or {}
    vulnerability = alert.get('security_vulnerability') or {}
    package = vulnerability.get('package') or {}
    patched = vulnerability.get('first_patched_version') or {}
    return {
        **_base(alert, 'dependabot', repo),
        'severity': _severity(advisory.get('severity') or vulnerability.get('severity')),
        'title': advisory.get('summary') or 'Vulnerable dependency',
        'package': package.get('name'),
        'ecosystem': package.get('ecosystem'),
        'fix_version': patched.get('identifier'),
        'identifier': advisory.get('cve_id') or advisory.get('ghsa_id'),
        'location': (alert.get('dependency') or {}).get('manifest_path'),
    }


def normalize_secret(alert, repo):
    # Deliberately not copying alert['secret']
    validity = alert.get('validity')
    return {
        **_base(alert, 'secret', repo),
        'severity': SECRET_SEVERITY,
        'title': alert.get('secret_type_display_name') or alert.get('secret_type') or 'Secret',
        'validity': validity if validity in ('active', 'inactive') else None,
        'publicly_leaked': bool(alert.get('publicly_leaked')),
    }


def normalize_code(alert, repo):
    rule = alert.get('rule') or {}
    instance = alert.get('most_recent_instance') or {}
    location = instance.get('location') or {}
    severity = rule.get('security_severity_level') or CODE_SEVERITY.get(rule.get('severity'))
    path = location.get('path')
    return {
        **_base(alert, 'code', repo),
        'severity': _severity(severity),
        'title': rule.get('description') or rule.get('name') or rule.get('id') or 'Code scanning alert',
        'tool': (alert.get('tool') or {}).get('name'),
        'location': f"{path}:{location['start_line']}" if path and location.get('start_line') else path,
    }


NORMALIZERS = {'dependabot': normalize_dependabot, 'secret': normalize_secret, 'code': normalize_code}


def fetch_alerts(full_name, kind, access_token):
    """Open alerts of one kind for one repository. Returns (alerts, truncated, error)."""
    owner, _, repo = full_name.partition('/')
    path = f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}/{KINDS[kind][1]}'
    data, error = github_api('GET', path, access_token, params={'state': 'open', 'per_page': PER_REPO})
    if error:
        return [], False, error
    if not isinstance(data, list):
        return [], False, 'Unexpected response from GitHub'
    return [NORMALIZERS[kind](alert, full_name) for alert in data], len(data) >= PER_REPO, None


def sort_key(alert):
    created = alert['created_at']
    return (SEVERITIES.index(alert['severity']), -(created.timestamp() if created else 0),
            alert['repo'].lower(), alert['number'] or 0)


def get_security_overview(repo_full_names, kinds, access_token):
    """
    Fetch alerts for every (repository, kind) pair in parallel.
    Returns {'alerts': [...] most severe first, 'coverage': {repo: {kind: {...}}}}.
    Each coverage cell is {'count', 'truncated', 'error'}.
    """
    jobs = [(repo, kind) for repo in repo_full_names for kind in kinds]
    if not jobs:
        return {'alerts': [], 'coverage': {}}
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
        results = list(pool.map(lambda job: fetch_alerts(job[0], job[1], access_token), jobs))

    alerts, coverage = [], {}
    for (repo, kind), (found, truncated, error) in zip(jobs, results):
        alerts.extend(found)
        coverage.setdefault(repo, {})[kind] = {'count': len(found), 'truncated': truncated, 'error': error}
    alerts.sort(key=sort_key)
    return {'alerts': alerts, 'coverage': coverage}


def severity_counts(alerts):
    counts = {severity: 0 for severity in SEVERITIES}
    for alert in alerts:
        counts[alert['severity']] += 1
    return counts


def unavailable(coverage):
    """Group (repo, kind) cells that couldn't be read by GitHub's reason: [(reason, [(repo, kind_label)])]."""
    groups = {}
    for repo, kinds in coverage.items():
        for kind, cell in kinds.items():
            if cell['error']:
                groups.setdefault(cell['error'], []).append((repo, KINDS[kind][0]))
    return sorted(((reason, sorted(cells)) for reason, cells in groups.items()), key=lambda group: -len(group[1]))
