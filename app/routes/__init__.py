"""Routes package.

Every route module registers on the single `main` blueprint so endpoint names
(e.g. url_for('main.home')) stay stable across modules.
"""
from flask import Blueprint

main_routes = Blueprint('main', __name__)

# Imported for their side effect of registering routes on main_routes.
from app.routes import (  # noqa: E402,F401
    repo_creation_routes,  # before auth_routes, which uses it in the OAuth callback
    auth_routes,
    repo_routes,
    issue_routes,
    pull_request_routes,
    branch_routes,
    content_routes,
    editor_routes,
    bulk_routes,
    cleanup_routes,
    inbox_routes,
)
