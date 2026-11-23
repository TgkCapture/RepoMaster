"""inbox_routes.py

Cross-repository inbox of open issues and pull requests (issue #37).
"""
import logging
from flask import render_template, request, session
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import get_github_repositories, search_issues
from app.controllers.inbox_controller import (
    AGES, MAX_RESULTS, PER_PAGE, SORTS, TYPES,
    build_search_query, label_text_color, parse_inbox_filters, to_inbox_items,
)

@main_routes.route('/inbox', methods=['GET'])
@login_required
def inbox():
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    repositories = get_github_repositories(access_token)
    if repositories is None:
        return "Failed to fetch repositories from GitHub", 500
    repo_full_names = sorted((r['full_name'] for r in repositories), key=str.lower)

    filters, warnings = parse_inbox_filters(request.args, set(repo_full_names))
    query = build_search_query(session.get('github_username'), session.get('github_account_type'), filters)
    _, sort, order = SORTS[filters['sort']]

    results, error = search_issues(query, access_token, sort=sort, order=order,
                                   page=filters['page'], per_page=PER_PAGE)
    items, hidden, total = [], 0, 0
    if results is not None:
        items, hidden = to_inbox_items(results.get('items', []), set(repo_full_names))
        total = min(results.get('total_count', 0), MAX_RESULTS)
        logging.info(f"Inbox query '{query}' returned {total} results (page {filters['page']}).")

    # Query args for pagination links, without the page number
    link_args = {key: value for key, value in filters.items() if key != 'page' and value}

    return render_template(
        'inbox.html',
        items=items, hidden=hidden, total=total, error=error, warnings=warnings,
        filters=filters, link_args=link_args, repo_full_names=repo_full_names,
        types=TYPES, ages=AGES, sorts=SORTS,
        has_next=filters['page'] * PER_PAGE < total, per_page=PER_PAGE,
        label_text_color=label_text_color,
    )
