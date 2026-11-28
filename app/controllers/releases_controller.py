"""releases_controller.py

Releases, tags and release assets (issue #43).
API calls go through repo_controller.github_api, which returns (json_or_None, error_message)
instead of raising. Asset uploads go to uploads.github.com, so they use requests directly.
"""
import logging
import re
from urllib.parse import quote
from app import github_http
from requests.exceptions import RequestException
from app.controllers.branch_management_controller import valid_branch
from app.controllers.file_editor_controller import upload_name
from app.controllers.repo_controller import REQUEST_TIMEOUT, _error_details, _github_error_message, github_api

MAX_NAME_LENGTH = 1024
MAX_BODY_LENGTH = 125000          # GitHub's limit for release notes
MAX_ASSETS_PER_UPLOAD = 10
SHA_PATTERN = re.compile(r'^[0-9a-f]{40}$')
MIME_PATTERN = re.compile(r'^[\w.+-]+/[\w.+-]+$')
MAKE_LATEST = {'legacy': 'Automatically (newest by date and version)', 'true': 'Yes', 'false': 'No'}


def _repo_path(owner, repo):
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


# --- Reading -----------------------------------------------------------------

def list_releases(owner, repo, access_token):
    """Up to 100 releases, newest first (drafts included). Returns (releases, error)."""
    return github_api('GET', f'{_repo_path(owner, repo)}/releases', access_token, params={'per_page': 100})


def list_tags(owner, repo, access_token):
    """Up to 100 tags. Returns (tags, error)."""
    return github_api('GET', f'{_repo_path(owner, repo)}/tags', access_token, params={'per_page': 100})


def get_release(owner, repo, release_id, access_token):
    return github_api('GET', f'{_repo_path(owner, repo)}/releases/{int(release_id)}', access_token)


def tags_without_release(tags, releases):
    """Tags that no release points at, in GitHub's order."""
    released = {release.get('tag_name') for release in releases}
    return [tag for tag in tags if tag.get('name') not in released]


# --- Validation --------------------------------------------------------------

def validate_release_form(form, branch_names):
    """
    Check the create / edit form. Returns (payload, error).
    The target only matters when the tag doesn't exist yet (GitHub then creates it there).
    """
    tag = (form.get('tag_name') or '').strip()
    if not valid_branch(tag):
        return None, "Enter a valid tag name, e.g. v1.2.0."
    target = (form.get('target_commitish') or '').strip()
    if target and target not in branch_names and not SHA_PATTERN.match(target):
        return None, "Choose a branch, or enter a full 40-character commit SHA."
    name = (form.get('name') or '').strip()
    if len(name) > MAX_NAME_LENGTH:
        return None, f"The title can be at most {MAX_NAME_LENGTH} characters."
    body = (form.get('body') or '').replace('\r\n', '\n')
    if len(body) > MAX_BODY_LENGTH:
        return None, f"The release notes can be at most {MAX_BODY_LENGTH} characters."
    make_latest = form.get('make_latest') or 'legacy'
    if make_latest not in MAKE_LATEST:
        return None, "Unknown 'latest release' option."

    payload = {
        'tag_name': tag,
        'name': name or tag,
        'body': body,
        'draft': form.get('draft') == 'on',
        'prerelease': form.get('prerelease') == 'on',
    }
    if target:
        payload['target_commitish'] = target
    if not payload['draft']:
        payload['make_latest'] = make_latest
    return payload, None


# --- Writing -----------------------------------------------------------------

def create_release(owner, repo, payload, access_token):
    return github_api('POST', f'{_repo_path(owner, repo)}/releases', access_token, json=payload)


def update_release(owner, repo, release_id, payload, access_token):
    return github_api('PATCH', f'{_repo_path(owner, repo)}/releases/{int(release_id)}', access_token, json=payload)


def delete_release(owner, repo, release, delete_tag, access_token):
    """
    Delete a release and, optionally, its tag (deleting a release keeps the tag).
    Returns (messages, error): messages are (category, text) pairs.
    """
    _, error = github_api('DELETE', f'{_repo_path(owner, repo)}/releases/{int(release["id"])}', access_token)
    if error:
        return None, error
    name = release.get('name') or release.get('tag_name')
    messages = [('success', f"Release {name} deleted.")]
    tag = release.get('tag_name')
    if delete_tag and tag and not release.get('draft'):
        _, error = github_api('DELETE', f'{_repo_path(owner, repo)}/git/refs/tags/{quote(tag, safe="/")}',
                              access_token)
        messages.append(('success', f"Tag {tag} deleted.") if not error
                        else ('error', f"The release was deleted, but the tag {tag} couldn't be: {error}"))
    return messages, None


def generate_notes(owner, repo, form, access_token):
    """
    Ask GitHub to write release notes for the tag in the form (from merged pull requests
    since the previous tag). Returns (notes_text, error).
    """
    tag = (form.get('tag_name') or '').strip()
    if not valid_branch(tag):
        return None, "Enter the tag name first, so GitHub knows which changes to include."
    payload = {'tag_name': tag}
    target = (form.get('target_commitish') or '').strip()
    if target:
        payload['target_commitish'] = target
    previous = (form.get('previous_tag_name') or '').strip()
    if previous:
        if not valid_branch(previous):
            return None, "The previous tag isn't a valid tag name."
        payload['previous_tag_name'] = previous
    result, error = github_api('POST', f'{_repo_path(owner, repo)}/releases/generate-notes', access_token,
                               json=payload)
    if error:
        return None, error
    return result.get('body', ''), None


# --- Assets ------------------------------------------------------------------

def upload_assets(owner, repo, release, files, access_token):
    """
    Upload files as release assets. Returns a list of (category, message), one per file;
    one failure doesn't stop the others.
    """
    files = [f for f in files if f and f.filename]
    if not files:
        return [('error', "Choose at least one file to upload.")]
    if len(files) > MAX_ASSETS_PER_UPLOAD:
        return [('error', f"Upload at most {MAX_ASSETS_PER_UPLOAD} files at a time.")]

    existing = {asset.get('name') for asset in release.get('assets') or []}
    upload_url = f'https://uploads.github.com{_repo_path(owner, repo)}/releases/{int(release["id"])}/assets'
    results = []
    for uploaded in files:
        name = upload_name(uploaded.filename)
        if not name:
            results.append(('error', f"'{uploaded.filename}' isn't a valid file name."))
            continue
        if name in existing:
            results.append(('error', f"{name}: an asset with this name already exists. Delete it first."))
            continue
        content_type = uploaded.mimetype if MIME_PATTERN.match(uploaded.mimetype or '') else 'application/octet-stream'
        try:
            response = github_http.post(upload_url, params={'name': name}, data=uploaded.read(), timeout=REQUEST_TIMEOUT,
                                     headers={'Authorization': f'Bearer {access_token}', 'Content-Type': content_type,
                                              'Accept': 'application/vnd.github+json'})
            response.raise_for_status()
            existing.add(name)
            results.append(('success', f"Uploaded {name}."))
        except RequestException as e:
            logging.error(f"Uploading asset {name} to {owner}/{repo} failed: {_error_details(e)}")
            results.append(('error', f"{name}: {_github_error_message(e)}"))
    return results


def delete_asset(owner, repo, release, asset_id, access_token):
    """Delete one of this release's assets. Returns (asset_name, error)."""
    asset = next((a for a in release.get('assets') or [] if a.get('id') == asset_id), None)
    if asset is None:
        return None, "That file isn't part of this release."
    _, error = github_api('DELETE', f'{_repo_path(owner, repo)}/releases/assets/{int(asset_id)}', access_token)
    return (None, error) if error else (asset.get('name'), None)


def human_size(size):
    """1234567 -> '1.2 MB'."""
    size = float(size or 0)
    for unit in ('B', 'KB', 'MB', 'GB'):
        if size < 1024 or unit == 'GB':
            return f"{size:.0f} {unit}" if unit == 'B' else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
