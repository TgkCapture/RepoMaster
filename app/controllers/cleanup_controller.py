"""cleanup_controller.py

Find repositories and branches that probably need cleaning up (issue #36).
"""
import logging
from datetime import datetime, timedelta, timezone
from app.controllers.repo_controller import get_repository, list_branches, compare_refs

DEFAULT_INACTIVE_MONTHS = 6
MAX_INACTIVE_MONTHS = 60
DAYS_PER_MONTH = 30


def parse_months(value):
    """The inactivity threshold from a query string, clamped to 1..MAX_INACTIVE_MONTHS."""
    try:
        months = int(value)
    except (TypeError, ValueError):
        return DEFAULT_INACTIVE_MONTHS
    return min(max(months, 1), MAX_INACTIVE_MONTHS)


def cutoff_date(months, now=None):
    now = now or datetime.now(timezone.utc)
    return now - timedelta(days=months * DAYS_PER_MONTH)


def parse_github_date(value):
    """Parse GitHub's ISO 8601 timestamps (e.g. '2024-01-31T12:00:00Z'). None if missing/invalid."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None


def analyze_repositories(repositories, months, now=None):
    """
    Sort repositories into cleanup candidates using only data from the repository list.
    Archived repositories are skipped: they are already cleaned up.

    Returns {'inactive': [...], 'empty': [...], 'forks': [...], 'archived_count': n}.
    Inactive entries are sorted oldest push first.
    """
    cutoff = cutoff_date(months, now)
    inactive, empty, forks = [], [], []
    archived_count = 0

    for repo in repositories:
        if repo.get('archived'):
            archived_count += 1
            continue

        pushed_at = parse_github_date(repo.get('pushed_at'))
        if pushed_at and pushed_at < cutoff:
            inactive.append({**repo, 'pushed_at_date': pushed_at})
        if repo.get('size') == 0:
            empty.append(repo)
        if repo.get('fork'):
            forks.append(repo)

    inactive.sort(key=lambda r: r['pushed_at_date'])
    return {'inactive': inactive, 'empty': empty, 'forks': forks, 'archived_count': archived_count}


def find_unmodified_forks(forks, access_token):
    """
    Check which forks have no commits of their own compared with their parent's default branch.
    Returns (unmodified, unchecked): unmodified forks get a 'parent' key; unchecked entries are
    {'repo', 'reason'} for forks that could not be compared.
    """
    unmodified, unchecked = [], []

    for fork in forks:
        owner, name = fork['full_name'].split('/', 1)
        details, error = get_repository(owner, name, access_token)
        parent = (details or {}).get('parent')
        if error or not parent:
            unchecked.append({'repo': fork, 'reason': error or "Parent repository not available"})
            continue

        parent_owner, parent_name = parent['full_name'].split('/', 1)
        comparison, error = compare_refs(parent_owner, parent_name, parent['default_branch'],
                                         f"{owner}:{details['default_branch']}", access_token)
        if error:
            unchecked.append({'repo': fork, 'reason': error})
            continue

        if comparison.get('ahead_by', 0) == 0:
            unmodified.append({**fork, 'parent': parent['full_name']})

    logging.info(f"Fork check: {len(unmodified)} unmodified, {len(unchecked)} unchecked of {len(forks)}.")
    return unmodified, unchecked


def analyze_branches(owner, repo, access_token, months, now=None):
    """
    Classify a repository's branches (up to 100) against its default branch:
    - merged: no commits that aren't already in the default branch
    - stale: has unmerged commits, but the newest one is older than the cutoff

    Returns (result, None) or (None, error_message), where result is
    {'default_branch', 'merged', 'stale', 'active_count', 'unchecked', 'truncated'}.
    Each merged/stale entry is {'name', 'protected', 'ahead_by', 'last_commit_date'}.
    """
    details, error = get_repository(owner, repo, access_token)
    if error:
        return None, error
    default_branch = details['default_branch']

    branches, error = list_branches(owner, repo, access_token)
    if error:
        return None, error

    cutoff = cutoff_date(months, now)
    result = {'default_branch': default_branch, 'merged': [], 'stale': [], 'active_count': 0,
              'unchecked': [], 'truncated': len(branches) >= 100}

    for branch in branches:
        name = branch['name']
        if name == default_branch:
            continue

        comparison, error = compare_refs(owner, repo, default_branch, name, access_token)
        if error:
            result['unchecked'].append({'name': name, 'reason': error})
            continue

        commits = comparison.get('commits') or []
        last_commit_date = None
        if commits:
            last_commit_date = parse_github_date(commits[-1].get('commit', {}).get('committer', {}).get('date'))

        entry = {'name': name, 'protected': bool(branch.get('protected')),
                 'ahead_by': comparison.get('ahead_by', 0), 'last_commit_date': last_commit_date}

        if entry['ahead_by'] == 0:
            result['merged'].append(entry)
        elif last_commit_date and last_commit_date < cutoff:
            result['stale'].append(entry)
        else:
            result['active_count'] += 1

    return result, None
