"""Tests for search, filters, sorting and pagination on the repositories page (issue #52)."""
import re

import pytest

from app.controllers.repo_list_controller import (
    PER_PAGE, active_filters, filter_and_sort, language_options, paginate, parse_repo_filters,
)
from app.routes import repo_routes


def repo(name, **fields):
    data = {'name': name, 'description': None, 'language': None, 'private': False, 'fork': False,
            'archived': False, 'stargazers_count': 0, 'forks_count': 0, 'updated_at': '2026-01-01T00:00:00Z',
            'owner': {'login': 'alice'}, 'language_color': '#ccc'}
    data.update(fields)
    return data


REPOS = [
    repo('api', description='REST backend', language='Python', stargazers_count=5,
         updated_at='2026-11-20T00:00:00Z', private=True, visibility='private'),
    repo('Website', description='Marketing site', language='JavaScript', stargazers_count=12,
         updated_at='2026-10-01T00:00:00Z'),
    repo('old-tool', language='Python', archived=True, updated_at='2025-01-01T00:00:00Z'),
    repo('forked-lib', description='Fork of a python lib', language='C', fork=True, stargazers_count=1,
         updated_at='2026-11-25T00:00:00Z'),
]


def names(repositories):
    return [r['name'] for r in repositories]


def filters(**values):
    return parse_repo_filters(values, language_options(REPOS))


# --- Parsing

def test_defaults():
    assert filters() == {'q': '', 'language': '', 'visibility': '', 'type': '', 'status': '', 'sort': 'updated'}


def test_unknown_values_fall_back_to_any():
    assert filters(language='Cobol', visibility='secret', type='x', status='y', sort='random') == filters()


def test_query_is_trimmed_and_capped():
    assert filters(q='  api  ')['q'] == 'api'
    assert len(filters(q='x' * 500)['q']) == 100


def test_language_options_are_sorted_and_unique():
    assert language_options(REPOS) == ['C', 'JavaScript', 'Python']


# --- Filtering

def test_search_matches_name_or_description_case_insensitively():
    assert names(filter_and_sort(REPOS, filters(q='WEB'))) == ['Website']
    assert names(filter_and_sort(REPOS, filters(q='backend'))) == ['api']
    assert set(names(filter_and_sort(REPOS, filters(q='python')))) == {'forked-lib'}


def test_search_treats_special_characters_literally():
    assert filter_and_sort(REPOS, filters(q='.*')) == []


def test_filter_by_language():
    assert set(names(filter_and_sort(REPOS, filters(language='Python')))) == {'api', 'old-tool'}


def test_filter_by_visibility():
    assert names(filter_and_sort(REPOS, filters(visibility='private'))) == ['api']
    assert 'api' not in names(filter_and_sort(REPOS, filters(visibility='public')))


def test_visibility_falls_back_to_private_flag():
    repositories = [repo('a', private=True), repo('b'), repo('c', visibility='internal', private=True)]
    assert names(filter_and_sort(repositories, filters(visibility='public'))) == ['b']
    assert set(names(filter_and_sort(repositories, filters(visibility='private')))) == {'a', 'c'}


def test_filter_forks_and_archived():
    assert names(filter_and_sort(REPOS, filters(type='forks'))) == ['forked-lib']
    assert 'forked-lib' not in names(filter_and_sort(REPOS, filters(type='sources')))
    assert names(filter_and_sort(REPOS, filters(status='archived'))) == ['old-tool']
    assert 'old-tool' not in names(filter_and_sort(REPOS, filters(status='active')))


def test_filters_combine():
    assert names(filter_and_sort(REPOS, filters(language='Python', status='active'))) == ['api']


# --- Sorting

def test_sort_by_last_updated_newest_first_by_default():
    assert names(filter_and_sort(REPOS, filters())) == ['forked-lib', 'api', 'Website', 'old-tool']


def test_sort_by_name_ignores_case():
    assert names(filter_and_sort(REPOS, filters(sort='name'))) == ['api', 'forked-lib', 'old-tool', 'Website']


def test_sort_by_stars_most_first_ties_by_name():
    assert names(filter_and_sort(REPOS, filters(sort='stars'))) == ['Website', 'api', 'forked-lib', 'old-tool']


def test_sort_copes_with_missing_fields():
    repositories = [repo('b', updated_at=None, stargazers_count=None), repo('a')]
    assert names(filter_and_sort(repositories, filters())) == ['a', 'b']
    assert names(filter_and_sort(repositories, filters(sort='stars'))) == ['a', 'b']


def test_filtering_does_not_change_the_input():
    original = list(REPOS)
    filter_and_sort(REPOS, filters(sort='name'))
    assert REPOS == original


# --- Pagination

@pytest.mark.parametrize('page, expected_page', [(1, 1), ('2', 2), (3, 3), (99, 3), (0, 1), (-4, 1), ('x', 1), (None, 1)])
def test_paginate_clamps_page(page, expected_page):
    items, number, pages = paginate(list(range(65)), page)
    assert (number, pages) == (expected_page, 3)
    assert items[0] == (expected_page - 1) * PER_PAGE


def test_paginate_last_page_and_empty_list():
    assert paginate(list(range(65)), 3)[0] == list(range(60, 65))
    assert paginate([], 1) == ([], 1, 1)


def test_active_filters_drop_defaults():
    assert active_filters(filters()) == {}
    assert active_filters(filters(q='api', sort='stars')) == {'q': 'api', 'sort': 'stars'}


# --- Page

@pytest.fixture
def listing(logged_in_client, monkeypatch):
    monkeypatch.setattr(repo_routes, 'get_installation_access_token', lambda: 'tok')
    def set_repositories(repositories):
        monkeypatch.setattr(repo_routes, 'get_github_repositories', lambda token: repositories)
    set_repositories(REPOS)
    logged_in_client.set_repositories = set_repositories
    return logged_in_client


def page(client, query=''):
    response = client.get('/github/repositories' + query)
    assert response.status_code == 200
    return response.data.decode()


def card_names(html):
    return re.findall(r'<h5 class="card-title">([^<\s]+)', html)


def test_page_shows_filter_form_and_count(listing):
    html = page(listing)
    assert 'name="q"' in html and 'name="language"' in html and 'name="sort"' in html
    assert '4 repositories' in html
    assert card_names(html) == ['forked-lib', 'api', 'Website', 'old-tool']
    assert '<option value="Python"' in html


def test_page_applies_filters_from_query_string(listing):
    html = page(listing, '?q=python&sort=name')
    assert card_names(html) == ['forked-lib']
    assert '1 of 4 repositories match' in html
    assert 'value="python"' in html
    assert '<option value="name" selected>' in html
    assert '>Clear</a>' in html


def test_page_shows_badges(listing):
    html = page(listing)
    assert 'Private</span>' in html and 'Fork</span>' in html and 'Archived</span>' in html


def test_page_with_no_matches_offers_to_clear(listing):
    html = page(listing, '?q=nothing-matches')
    assert 'No repositories match these filters.' in html
    assert 'Start by connecting' not in html


def test_page_without_repositories_hides_form(listing):
    listing.set_repositories([])
    html = page(listing)
    assert 'Start by connecting' in html
    assert 'name="q"' not in html


def test_page_paginates_and_links_keep_filters(listing):
    listing.set_repositories([repo(f'repo-{n:03}', language='Go') for n in range(70)])
    html = page(listing, '?sort=name&language=Go&page=2')
    assert card_names(html) == [f'repo-{n:03}' for n in range(30, 60)]
    assert 'page 2 of 3' in html
    assert 'aria-current="page">2</a>' in html
    links = re.findall(r'href="(/github/repositories\?[^"]+)"', html)
    assert '/github/repositories?page=3&amp;language=Go&amp;sort=name' in links


def test_page_out_of_range_shows_last_page(listing):
    listing.set_repositories([repo(f'repo-{n:03}') for n in range(35)])
    html = page(listing, '?sort=name&page=50')
    assert card_names(html) == [f'repo-{n:03}' for n in range(30, 35)]


def test_single_page_has_no_pager(listing):
    assert 'Repository pages' not in page(listing)


def test_search_text_is_escaped(listing):
    html = page(listing, '?q=%3Cscript%3E')
    assert 'value="&lt;script&gt;"' in html
    assert 'value="<script>' not in html
