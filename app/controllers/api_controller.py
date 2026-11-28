"""api_controller.py

Data for the JSON API (issue #53): GitHub objects trimmed to stable, documented shapes
(see OpenAPI.json), plus repository contents. Everything returns plain dicts and lists;
app/routes/api_routes.py turns them into responses.
"""
import base64
import binascii
from urllib.parse import quote

from app.controllers.file_editor_controller import decode_text, normalize_path
from app.controllers.repo_controller import github_api

MAX_REF_LENGTH = 255


def _login(user):
    return (user or {}).get('login')


def repository_summary(repo):
    return {
        'id': repo.get('id'),
        'name': repo.get('name'),
        'full_name': repo.get('full_name'),
        'owner': _login(repo.get('owner')),
        'description': repo.get('description'),
        'private': bool(repo.get('private')),
        'visibility': repo.get('visibility') or ('private' if repo.get('private') else 'public'),
        'fork': bool(repo.get('fork')),
        'archived': bool(repo.get('archived')),
        'language': repo.get('language'),
        'stars': repo.get('stargazers_count') or 0,
        'forks': repo.get('forks_count') or 0,
        'open_issues': repo.get('open_issues_count') or 0,
        'default_branch': repo.get('default_branch'),
        'html_url': repo.get('html_url'),
        'updated_at': repo.get('updated_at'),
        'pushed_at': repo.get('pushed_at'),
    }


def issue_summary(issue):
    return {
        'number': issue.get('number'),
        'title': issue.get('title'),
        'state': issue.get('state'),
        'author': _login(issue.get('user')),
        'labels': [label.get('name') for label in issue.get('labels') or [] if isinstance(label, dict)],
        'assignees': [_login(user) for user in issue.get('assignees') or []],
        'comments': issue.get('comments') or 0,
        'created_at': issue.get('created_at'),
        'updated_at': issue.get('updated_at'),
        'closed_at': issue.get('closed_at'),
        'html_url': issue.get('html_url'),
    }


def pull_request_summary(pull):
    return {
        'number': pull.get('number'),
        'title': pull.get('title'),
        'state': pull.get('state'),
        'draft': bool(pull.get('draft')),
        'author': _login(pull.get('user')),
        'head': (pull.get('head') or {}).get('ref'),
        'base': (pull.get('base') or {}).get('ref'),
        'created_at': pull.get('created_at'),
        'updated_at': pull.get('updated_at'),
        'merged_at': pull.get('merged_at'),
        'html_url': pull.get('html_url'),
    }


def branch_summary(branch):
    return {
        'name': branch.get('name'),
        'protected': bool(branch.get('protected')),
        'sha': (branch.get('commit') or {}).get('sha'),
    }


def _entry(item):
    return {'name': item.get('name'), 'path': item.get('path'), 'type': item.get('type'),
            'size': item.get('size') or 0, 'sha': item.get('sha')}


def file_summary(data):
    """A file with its content: UTF-8 text when it is text, base64 otherwise, null when over 1 MB."""
    result = {'type': 'file', 'path': data.get('path'), 'name': data.get('name'), 'sha': data.get('sha'),
              'size': data.get('size') or 0, 'html_url': data.get('html_url'),
              'encoding': None, 'content': None}
    if data.get('encoding') != 'base64':
        return result  # GitHub leaves content out for files over 1 MB
    raw_b64 = (data.get('content') or '').replace('\n', '')
    try:
        raw = base64.b64decode(raw_b64)
    except (binascii.Error, ValueError):
        return result
    text = decode_text(raw)
    if text is None:
        result.update(encoding='base64', content=raw_b64)
    else:
        result.update(encoding='utf-8', content=text)
    return result


def validate_ref(ref):
    """An optional branch, tag or commit. Returns (ref or None, error)."""
    ref = (ref or '').strip()
    if not ref:
        return None, None
    if len(ref) > MAX_REF_LENGTH or any(ch in ref for ch in ' ~^:?*[\\') or '..' in ref:
        return None, "Invalid ref."
    return ref, None


def get_contents(owner, repo, path, ref, access_token):
    """
    A directory listing ({'type': 'dir', 'path', 'entries'}) or a file (see file_summary).
    Returns (data, error).
    """
    if path:
        path = normalize_path(path)
        if path is None:
            return None, "Invalid path."
    api_path = f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}/contents/{quote(path or "", safe="/")}'
    data, error = github_api('GET', api_path, access_token, params={'ref': ref} if ref else {})
    if error:
        return None, error
    if isinstance(data, list):
        entries = sorted((_entry(item) for item in data), key=lambda e: (e['type'] != 'dir', (e['name'] or '').lower()))
        return {'type': 'dir', 'path': path or '', 'entries': entries}, None
    if data.get('type') != 'file':
        return {'type': data.get('type'), 'path': data.get('path'), 'name': data.get('name'),
                'sha': data.get('sha'), 'size': data.get('size') or 0, 'html_url': data.get('html_url')}, None
    return file_summary(data), None
