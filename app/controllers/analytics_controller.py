"""analytics_controller.py

Repository analytics (issue #44): traffic, commit activity, contributors and languages.
Every section is fetched independently, so one failing (e.g. traffic needs admin access)
doesn't hide the others. Calls go through repo_controller.github_api.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import quote
from app.controllers.repo_controller import github_api

STATS_ATTEMPTS = 3
STATS_RETRY_SECONDS = 2
TOP_CONTRIBUTORS = 20
COMPUTING = "GitHub is still computing these statistics. Reload the page in a minute."


def _repo_path(owner, repo):
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


def fetch_stats(path, access_token, sleep=time.sleep):
    """
    GET a /stats endpoint. GitHub answers 202 with an empty body while it computes them,
    so retry a few times. Returns (list, error); an empty repository gives ([], None).
    """
    for attempt in range(STATS_ATTEMPTS):
        data, error = github_api('GET', path, access_token)
        if error:
            return None, error
        if isinstance(data, list):
            return data, None
        if data is None:  # 204: no commits
            return [], None
        if attempt < STATS_ATTEMPTS - 1:  # 202: {} while computing
            sleep(STATS_RETRY_SECONDS * (attempt + 1))
    return None, COMPUTING


def _day(timestamp):
    """'2026-11-20T00:00:00Z' -> '2026-11-20'."""
    return (timestamp or '')[:10]


def summarize_traffic(data):
    """Views or clones: totals plus one point per day."""
    data = data or {}
    points = data.get('views') or data.get('clones') or []
    return {
        'count': data.get('count', 0),
        'uniques': data.get('uniques', 0),
        'days': [_day(p.get('timestamp')) for p in points],
        'totals': [p.get('count', 0) for p in points],
        'unique_totals': [p.get('uniques', 0) for p in points],
    }


def summarize_commit_activity(weeks):
    """Weekly commit totals for the last year (oldest first)."""
    weeks = weeks or []
    return {
        'weeks': [datetime.fromtimestamp(w.get('week', 0), tz=timezone.utc).strftime('%Y-%m-%d') for w in weeks],
        'totals': [w.get('total', 0) for w in weeks],
        'total': sum(w.get('total', 0) for w in weeks),
    }


def summarize_contributors(contributors):
    """Top contributors by commits, with lines added / removed."""
    rows = []
    for entry in contributors or []:
        author = entry.get('author') or {}
        weeks = entry.get('weeks') or []
        rows.append({
            'login': author.get('login') or 'unknown',
            'html_url': author.get('html_url'),
            'commits': entry.get('total', 0),
            'additions': sum(w.get('a', 0) for w in weeks),
            'deletions': sum(w.get('d', 0) for w in weeks),
        })
    rows.sort(key=lambda row: (-row['commits'], row['login'].lower()))
    return rows[:TOP_CONTRIBUTORS]


def summarize_languages(languages):
    """Languages by share of bytes, largest first, as percentages (one decimal)."""
    languages = languages or {}
    total = sum(languages.values())
    if not total:
        return []
    rows = [{'name': name, 'bytes': size, 'percent': round(size * 100 / total, 1)}
            for name, size in languages.items()]
    rows.sort(key=lambda row: -row['bytes'])
    return rows


def get_analytics(owner, repo, access_token, sleep=time.sleep):
    """
    All analytics sections. Each value is {'data': ..., 'error': message_or_None}.
    Requests run in parallel; the /stats ones may wait for GitHub to compute them.
    """
    base = _repo_path(owner, repo)
    plain = {
        'views': (f'{base}/traffic/views', summarize_traffic),
        'clones': (f'{base}/traffic/clones', summarize_traffic),
        'referrers': (f'{base}/traffic/popular/referrers', lambda rows: rows or []),
        'paths': (f'{base}/traffic/popular/paths', lambda rows: rows or []),
        'languages': (f'{base}/languages', summarize_languages),
    }
    stats = {
        'commit_activity': (f'{base}/stats/commit_activity', summarize_commit_activity),
        'contributors': (f'{base}/stats/contributors', summarize_contributors),
    }

    def run_plain(path):
        return github_api('GET', path, access_token)

    def run_stats(path):
        return fetch_stats(path, access_token, sleep)

    with ThreadPoolExecutor(max_workers=len(plain) + len(stats)) as pool:
        futures = {key: pool.submit(run_plain, path) for key, (path, _) in plain.items()}
        futures.update({key: pool.submit(run_stats, path) for key, (path, _) in stats.items()})
        results = {key: future.result() for key, future in futures.items()}

    summarizers = {key: summarize for key, (_, summarize) in {**plain, **stats}.items()}
    sections = {}
    for key, (data, error) in results.items():
        sections[key] = {'data': None if error else summarizers[key](data), 'error': error}
    return sections
