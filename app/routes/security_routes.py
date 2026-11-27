"""security_routes.py

Security overview across repositories (issue #47).
"""
from flask import render_template, request
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import get_github_repositories
from app.controllers.security_controller import (
    KINDS, SEVERITIES, get_security_overview, parse_security_filters, severity_counts, unavailable,
)


@main_routes.route('/security', methods=['GET'])
@login_required
def security_overview():
    """Open Dependabot, secret scanning and code scanning alerts, most severe first."""
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    repositories = get_github_repositories(access_token)
    if repositories is None:
        return "Failed to fetch repositories from GitHub", 500
    repo_full_names = sorted((r['full_name'] for r in repositories), key=str.lower)

    filters, warnings = parse_security_filters(request.args, set(repo_full_names))
    # Only ask GitHub for what the repo / kind filters will show
    repos = [filters['repo']] if filters['repo'] else repo_full_names
    kinds = [filters['kind']] if filters['kind'] else list(KINDS)
    overview = get_security_overview(repos, kinds, access_token)

    counts = severity_counts(overview['alerts'])
    alerts = [a for a in overview['alerts'] if not filters['severity'] or a['severity'] == filters['severity']]
    link_args = {key: value for key, value in filters.items() if key != 'severity' and value}

    return render_template(
        'security.html',
        alerts=alerts, counts=counts, total=len(overview['alerts']),
        unavailable=unavailable(overview['coverage']),
        truncated=[(repo, KINDS[kind][0]) for repo, cells in overview['coverage'].items()
                   for kind, cell in cells.items() if cell['truncated']],
        filters=filters, warnings=warnings, link_args=link_args,
        repo_full_names=repo_full_names, kinds=KINDS, severities=SEVERITIES,
    )
