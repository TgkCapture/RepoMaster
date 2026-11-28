"""repo_list_controller.py

Search, filtering, sorting and pagination for the repositories page (issue #52).

Everything works on the list get_github_repositories already fetched, so changing a
filter or a page never costs extra GitHub requests beyond loading the list itself.
"""

PER_PAGE = 30
MAX_QUERY_LENGTH = 100

VISIBILITIES = ('public', 'private')
TYPES = ('sources', 'forks')
STATUSES = ('active', 'archived')

# sort key -> (label, function giving the sort value, newest/biggest first?)
SORTS = {
    'updated': ('Last updated', lambda repo: repo.get('updated_at') or '', True),
    'name': ('Name', lambda repo: (repo.get('name') or '').lower(), False),
    'stars': ('Stars', lambda repo: repo.get('stargazers_count') or 0, True),
}
DEFAULT_SORT = 'updated'

DEFAULT_FILTERS = {'q': '', 'language': '', 'visibility': '', 'type': '', 'status': '', 'sort': DEFAULT_SORT}


def language_options(repositories):
    """The languages used by the repositories, alphabetically."""
    return sorted({repo['language'] for repo in repositories if repo.get('language')}, key=str.lower)


def parse_repo_filters(args, languages):
    """Read the filters from the query string. Unknown values fall back to "any"."""
    def choice(key, options):
        value = (args.get(key) or '').strip()
        return value if value in options else ''

    return {
        'q': (args.get('q') or '').strip()[:MAX_QUERY_LENGTH],
        'language': choice('language', languages),
        'visibility': choice('visibility', VISIBILITIES),
        'type': choice('type', TYPES),
        'status': choice('status', STATUSES),
        'sort': choice('sort', SORTS) or DEFAULT_SORT,
    }


def _visibility(repo):
    return repo.get('visibility') or ('private' if repo.get('private') else 'public')


def _matches(repo, filters):
    query = filters['q'].lower()
    if query and query not in (repo.get('name') or '').lower() \
            and query not in (repo.get('description') or '').lower():
        return False
    if filters['language'] and repo.get('language') != filters['language']:
        return False
    if filters['visibility'] == 'private' and _visibility(repo) == 'public':
        return False
    if filters['visibility'] == 'public' and _visibility(repo) != 'public':
        return False
    if filters['type'] and bool(repo.get('fork')) != (filters['type'] == 'forks'):
        return False
    if filters['status'] and bool(repo.get('archived')) != (filters['status'] == 'archived'):
        return False
    return True


def filter_and_sort(repositories, filters):
    """The repositories matching the filters, in the chosen order (ties broken by name)."""
    _, key, descending = SORTS[filters['sort']]
    matching = [repo for repo in repositories if _matches(repo, filters)]
    matching.sort(key=lambda repo: (repo.get('name') or '').lower())
    matching.sort(key=key, reverse=descending)
    return matching


def paginate(items, page, per_page=PER_PAGE):
    """Returns (items on the page, page number, number of pages). Out-of-range pages are clamped."""
    pages = max(1, -(-len(items) // per_page))
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1
    page = min(max(page, 1), pages)
    start = (page - 1) * per_page
    return items[start:start + per_page], page, pages


def active_filters(filters):
    """The filters that differ from the defaults, for building links that keep them."""
    return {key: value for key, value in filters.items() if value and value != DEFAULT_FILTERS[key]}
