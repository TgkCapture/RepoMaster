"""inbox_controller.py

Cross-repository inbox of open issues and pull requests (issue #37), built on the
GitHub search API: one request per page instead of one per repository.
"""
import re
from datetime import datetime, timedelta, timezone
from app.controllers.cleanup_controller import parse_github_date

PER_PAGE = 50
MAX_RESULTS = 1000  # GitHub search never returns more than this

TYPES = {'': 'Issues and pull requests', 'issue': 'Issues', 'pr': 'Pull requests'}

# key -> (label, comparison, days) for the `created:` qualifier
AGES = {
    '': ('Any age', None, None),
    'new7': ('Opened in the last 7 days', '>=', 7),
    'new30': ('Opened in the last 30 days', '>=', 30),
    'old30': ('Open longer than 30 days', '<', 30),
    'old90': ('Open longer than 90 days', '<', 90),
    'old365': ('Open longer than a year', '<', 365),
}

# key -> (label, GitHub sort, order)
SORTS = {
    'updated': ('Recently updated', 'updated', 'desc'),
    'newest': ('Newest', 'created', 'desc'),
    'oldest': ('Oldest', 'created', 'asc'),
    'stale': ('Least recently updated', 'updated', 'asc'),
}

LOGIN_PATTERN = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?$')
LABEL_PATTERN = re.compile(r'^[^"\\\r\n]{1,50}$')
COLOR_PATTERN = re.compile(r'^[0-9a-fA-F]{6}$')


def parse_inbox_filters(args, repo_full_names):
    """
    Read and validate inbox filters from query-string args.
    Invalid values are dropped and reported. Returns (filters, warnings).
    """
    warnings = []

    def choice(key, options, default=''):
        value = (args.get(key) or default).strip()
        if value not in options:
            warnings.append(f"Ignored unknown {key} '{value}'.")
            return default
        return value

    filters = {
        'type': choice('type', TYPES),
        'age': choice('age', AGES),
        'sort': choice('sort', SORTS, 'updated'),
        'repo': (args.get('repo') or '').strip(),
        'label': (args.get('label') or '').strip(),
        'author': (args.get('author') or '').strip().lstrip('@'),
    }

    if filters['repo'] and filters['repo'] not in repo_full_names:
        warnings.append(f"Ignored repository '{filters['repo']}': it is not available to this installation.")
        filters['repo'] = ''
    if filters['label'] and not LABEL_PATTERN.match(filters['label']):
        warnings.append("Ignored label: labels can't contain quotes or backslashes and are at most 50 characters.")
        filters['label'] = ''
    if filters['author'] and not LOGIN_PATTERN.match(filters['author']):
        warnings.append(f"Ignored author '{filters['author']}': not a valid GitHub username.")
        filters['author'] = ''

    try:
        filters['page'] = max(1, int(args.get('page', 1)))
    except (TypeError, ValueError):
        filters['page'] = 1
    filters['page'] = min(filters['page'], MAX_RESULTS // PER_PAGE)

    return filters, warnings


def build_search_query(owner, account_type, filters, now=None):
    """GitHub search query for the open issues/PRs matching the filters."""
    now = now or datetime.now(timezone.utc)
    terms = ['is:open']

    if filters['repo']:
        terms.append(f"repo:{filters['repo']}")
    else:
        terms.append(f"{'org' if account_type == 'Organization' else 'user'}:{owner}")

    if filters['type'] == 'issue':
        terms.append('is:issue')
    elif filters['type'] == 'pr':
        terms.append('is:pr')

    if filters['label']:
        terms.append(f'label:"{filters["label"]}"')
    if filters['author']:
        terms.append(f"author:{filters['author']}")

    _, comparison, days = AGES[filters['age']]
    if comparison:
        date = (now - timedelta(days=days)).date().isoformat()
        terms.append(f"created:{comparison}{date}")

    return ' '.join(terms)


def time_ago(moment, now=None):
    """Short relative time, e.g. 'just now', '5 minutes ago', '3 days ago', '2 years ago'."""
    if not moment:
        return 'unknown'
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((now - moment).total_seconds()))
    for unit, size in (('year', 365 * 86400), ('month', 30 * 86400), ('day', 86400),
                       ('hour', 3600), ('minute', 60)):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return 'just now'


def to_inbox_items(search_items, allowed_repos, now=None):
    """
    Convert search results to display rows, keeping only repositories the installation can access.
    Returns (items, hidden_count).
    """
    items, hidden = [], 0
    for result in search_items:
        full_name = result.get('repository_url', '').split('/repos/', 1)[-1]
        if full_name not in allowed_repos:
            hidden += 1
            continue

        created = parse_github_date(result.get('created_at'))
        updated = parse_github_date(result.get('updated_at'))
        items.append({
            'kind': 'pr' if 'pull_request' in result else 'issue',
            'draft': bool(result.get('draft')),
            'repo': full_name,
            'repo_name': full_name.split('/', 1)[-1],
            'number': result.get('number'),
            'title': result.get('title', ''),
            'html_url': result.get('html_url'),
            'author': (result.get('user') or {}).get('login', ''),
            'labels': [{'name': label.get('name', ''),
                        'color': label['color'] if COLOR_PATTERN.match(label.get('color') or '') else 'cccccc'}
                       for label in result.get('labels', [])],
            'comments': result.get('comments', 0),
            'created_ago': time_ago(created, now),
            'updated_ago': time_ago(updated, now),
            'created_at': created,
        })
    return items, hidden


def label_text_color(hex_color):
    """Black or white text, whichever reads better on the label's background color."""
    red, green, blue = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return '#000000' if (red * 299 + green * 587 + blue * 114) / 1000 > 140 else '#ffffff'
