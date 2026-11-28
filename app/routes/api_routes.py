"""api_routes.py

The read-only JSON API, /api/v1 (issue #53). Documented in OpenAPI.json, which is served
at /api/v1/openapi.json and shown at /api/docs.

Requests authenticate with a RepoMaster API token (`Authorization: Bearer rm_...`, created
at /api/tokens) and act as the token's installation. The browser session is never used,
so the API can't be driven by a signed-in user's cookies.
"""
import json
import logging
import os

from flask import Blueprint, current_app, g, jsonify, request

from app.controllers.api_controller import (
    branch_summary, get_contents, issue_summary, pull_request_summary, repository_summary, validate_ref,
)
from app.controllers.api_token_controller import authenticate_token
from app.controllers.auth_controller import get_installation_access_token
from app.controllers.branch_management_controller import valid_names
from app.controllers.issues_controller import list_issues, parse_state as parse_issue_state
from app.controllers.pull_requests_controller import list_pull_requests, parse_state as parse_pull_state
from app.controllers.repo_controller import get_github_repositories, get_repository, list_branches
from app.controllers.repo_list_controller import (
    filter_and_sort, language_options, paginate, parse_repo_filters,
)

api_v1 = Blueprint('api_v1', __name__, url_prefix='/api/v1')

PUBLIC_ENDPOINTS = {'api_v1.openapi_spec'}
DEFAULT_PER_PAGE = 30
MAX_PER_PAGE = 100


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def error_response(status, message):
    response = jsonify({'error': {'status': status, 'message': message}})
    response.status_code = status
    if status == 401:
        response.headers['WWW-Authenticate'] = 'Bearer realm="RepoMaster API"'
    return response


@api_v1.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.status, error.message)


@api_v1.app_errorhandler(404)
def not_found(error):
    if request.path.startswith(api_v1.url_prefix + '/'):
        return error_response(404, "Not found.")
    return error


@api_v1.app_errorhandler(405)
def method_not_allowed(error):
    if request.path.startswith(api_v1.url_prefix + '/'):
        return error_response(405, "This endpoint is read-only; only GET is supported.")
    return error


@api_v1.before_request
def authenticate():
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    header = request.headers.get('Authorization', '')
    scheme, _, token = header.partition(' ')
    if scheme.lower() != 'bearer' or not token.strip():
        return error_response(401, "Send an API token as 'Authorization: Bearer <token>'. Create one at /api/tokens.")
    record = authenticate_token(token.strip())
    if record is None:
        return error_response(401, "Invalid or revoked API token.")
    g.api_token = record
    return None


@api_v1.after_request
def no_store(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def github_token():
    """An installation access token for the API token's installation (fetched once per request)."""
    if 'github_token' not in g:
        g.github_token = get_installation_access_token(g.api_token['installation_id'])
    if not g.github_token:
        raise ApiError(502, "Couldn't authenticate with GitHub for this account. Is the app still installed?")
    return g.github_token


def check_repository(owner, repo):
    """Only repositories of the token's account are served."""
    if not valid_names(owner, repo) or owner.lower() != (g.api_token['account'] or '').lower():
        raise ApiError(404, "Repository not found for this token's account.")


def github_result(data, error):
    if error:
        if error == 'Not Found':
            raise ApiError(404, "Not found on GitHub.")
        raise ApiError(502, f"GitHub error: {error}")
    return data


def int_arg(name, default, minimum, maximum):
    value = request.args.get(name)
    if value in (None, ''):
        return default
    try:
        number = int(value)
    except ValueError:
        raise ApiError(400, f"'{name}' must be a whole number.")
    if not minimum <= number <= maximum:
        raise ApiError(400, f"'{name}' must be between {minimum} and {maximum}.")
    return number


def listing(items):
    return jsonify({'count': len(items), 'items': items})


# --- Endpoints ---------------------------------------------------------------

@api_v1.route('/openapi.json', methods=['GET'])
def openapi_spec():
    """The API description, from OpenAPI.json in the project root."""
    path = os.path.join(os.path.dirname(current_app.root_path), 'OpenAPI.json')
    try:
        with open(path, encoding='utf-8') as spec_file:
            return jsonify(json.load(spec_file))
    except (OSError, ValueError) as e:
        logging.error(f"Couldn't load OpenAPI.json: {e}")
        return error_response(500, "The API description is unavailable.")


@api_v1.route('/me', methods=['GET'])
def me():
    token = g.api_token
    return jsonify({'account': token['account'], 'account_type': token['account_type'],
                    'installation_id': token['installation_id'],
                    'token': {'name': token['name'], 'created_by': token['created_by']}})


@api_v1.route('/repos', methods=['GET'])
def repositories():
    repositories = get_github_repositories(github_token())
    if repositories is None:
        raise ApiError(502, "Couldn't fetch repositories from GitHub.")
    filters = parse_repo_filters(request.args, language_options(repositories))
    per_page = int_arg('per_page', DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)
    page = int_arg('page', 1, 1, 10000)
    matching = filter_and_sort(repositories, filters)
    items, page, pages = paginate(matching, page, per_page)
    return jsonify({'total': len(repositories), 'matching': len(matching), 'page': page, 'pages': pages,
                    'per_page': per_page, 'filters': filters, 'items': [repository_summary(r) for r in items]})


@api_v1.route('/repos/<owner>/<repo>', methods=['GET'])
def repository(owner, repo):
    check_repository(owner, repo)
    return jsonify(repository_summary(github_result(*get_repository(owner, repo, github_token()))))


@api_v1.route('/repos/<owner>/<repo>/issues', methods=['GET'])
def issues(owner, repo):
    check_repository(owner, repo)
    state = parse_issue_state(request.args.get('state'))
    issues = github_result(*list_issues(owner, repo, github_token(), state))
    return listing([issue_summary(issue) for issue in issues])


@api_v1.route('/repos/<owner>/<repo>/pulls', methods=['GET'])
def pull_requests(owner, repo):
    check_repository(owner, repo)
    state = parse_pull_state(request.args.get('state'))
    pulls = github_result(*list_pull_requests(owner, repo, github_token(), state))
    return listing([pull_request_summary(pull) for pull in pulls or []])


@api_v1.route('/repos/<owner>/<repo>/branches', methods=['GET'])
def branches(owner, repo):
    check_repository(owner, repo)
    branches = github_result(*list_branches(owner, repo, github_token()))
    return listing([branch_summary(branch) for branch in branches or []])


@api_v1.route('/repos/<owner>/<repo>/contents', defaults={'path': ''}, methods=['GET'])
@api_v1.route('/repos/<owner>/<repo>/contents/<path:path>', methods=['GET'])
def contents(owner, repo, path):
    check_repository(owner, repo)
    ref, error = validate_ref(request.args.get('ref'))
    if error:
        raise ApiError(400, error)
    data, error = get_contents(owner, repo, path, ref, github_token())
    if error == "Invalid path.":
        raise ApiError(400, error)
    return jsonify(github_result(data, error))
