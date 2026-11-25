"""analytics_routes.py

Repository analytics page (issue #44).
"""
from flask import render_template
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.branch_management_controller import valid_names
from app.controllers.analytics_controller import get_analytics


@main_routes.route('/repos/<owner>/<repo>/analytics', methods=['GET'])
@login_required
def repository_analytics(owner, repo):
    """Traffic, commit activity, contributors and languages for one repository."""
    if not valid_names(owner, repo):
        return "Invalid repository name", 400
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    sections = get_analytics(owner, repo, access_token)
    chart_data = {
        'views': sections['views']['data'],
        'clones': sections['clones']['data'],
        'commit_activity': sections['commit_activity']['data'],
        'languages': sections['languages']['data'],
    }
    return render_template('analytics.html', owner=owner, repo=repo, sections=sections, chart_data=chart_data)
