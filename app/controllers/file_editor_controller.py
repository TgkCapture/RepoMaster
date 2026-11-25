"""file_editor_controller.py

In-browser file editor and uploads (issue #42).

Changes are committed with the Git Data API (blobs -> tree -> commit -> ref), so several
files can go into one commit, binary files are handled as base64, and the commit can
target an existing branch or a new one. All GitHub calls go through repo_controller.github_api,
which returns (json_or_None, error_message) instead of raising.
"""
import base64
import binascii
import posixpath
from urllib.parse import quote
from app.controllers.branch_management_controller import valid_branch, valid_names
from app.controllers.repo_controller import github_api

MAX_EDITABLE_BYTES = 1024 * 1024           # the contents API only returns content up to 1 MB
MAX_UPLOAD_FILES = 20
MAX_UPLOAD_BYTES = 25 * 1024 * 1024        # per request; also Flask's MAX_CONTENT_LENGTH
MAX_PATH_LENGTH = 1024
MAX_MESSAGE_LENGTH = 65536
FILE_MODE = '100644'
MISSING = object()  # expected_sha value meaning "don't check"

# File extension -> (CodeMirror mode scripts to load, mode/MIME to use)
EDITOR_MODES = {
    'py': (['python'], 'python'),
    'js': (['javascript'], 'javascript'), 'mjs': (['javascript'], 'javascript'), 'cjs': (['javascript'], 'javascript'),
    'json': (['javascript'], 'application/json'),
    'ts': (['javascript'], 'text/typescript'),
    'html': (['xml', 'javascript', 'css', 'htmlmixed'], 'htmlmixed'),
    'htm': (['xml', 'javascript', 'css', 'htmlmixed'], 'htmlmixed'),
    'xml': (['xml'], 'xml'), 'svg': (['xml'], 'xml'),
    'css': (['css'], 'css'), 'scss': (['css'], 'text/x-scss'),
    'md': (['markdown'], 'markdown'), 'markdown': (['markdown'], 'markdown'),
    'yml': (['yaml'], 'yaml'), 'yaml': (['yaml'], 'yaml'),
    'sh': (['shell'], 'shell'), 'bash': (['shell'], 'shell'),
    'go': (['go'], 'go'),
    'sql': (['sql'], 'text/x-sql'),
    'c': (['clike'], 'text/x-csrc'), 'h': (['clike'], 'text/x-csrc'),
    'cpp': (['clike'], 'text/x-c++src'), 'hpp': (['clike'], 'text/x-c++src'),
    'java': (['clike'], 'text/x-java'), 'cs': (['clike'], 'text/x-csharp'), 'kt': (['clike'], 'text/x-kotlin'),
    'rb': (['ruby'], 'ruby'),
    'toml': (['toml'], 'toml'),
}


# --- Paths and modes ---------------------------------------------------------

def normalize_path(path):
    """
    A repository file path without leading/trailing slashes, or None if it's unsafe
    (empty segments, '.', '..', '.git', control characters or too long).
    """
    path = (path or '').strip().strip('/')
    if not path or len(path) > MAX_PATH_LENGTH or any(ord(ch) < 32 or ch == '\x7f' for ch in path):
        return None
    segments = path.split('/')
    if any(seg in ('', '.', '..') or seg.lower() == '.git' or seg != seg.strip() for seg in segments):
        return None
    return path


def normalize_directory(path):
    """Like normalize_path, but '' (the repository root) is allowed. None if unsafe."""
    path = (path or '').strip().strip('/')
    return '' if not path else normalize_path(path)


def upload_name(filename):
    """The file name part of an uploaded file's name (browsers may send a full path)."""
    name = (filename or '').replace('\\', '/').rsplit('/', 1)[-1].strip()
    return name if normalize_path(name) == name else None


def editor_mode(path):
    """(CodeMirror mode scripts, mode) for a file name; plain text when unknown."""
    name = posixpath.basename(path or '').lower()
    extension = name.rsplit('.', 1)[-1] if '.' in name else ''
    return EDITOR_MODES.get(extension, ([], 'text/plain'))


def is_markdown(path):
    return editor_mode(path)[1] == 'markdown'


def _repo_path(owner, repo):
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


def _contents_path(owner, repo, path):
    return f'{_repo_path(owner, repo)}/contents/{quote(path, safe="/")}'


# --- Loading a file ----------------------------------------------------------

def decode_text(raw):
    """UTF-8 text for editing, or None if the bytes look binary."""
    if b'\x00' in raw:
        return None
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def load_file(owner, repo, path, ref, access_token):
    """
    Load a file for editing. Returns (file, error) where file has path, sha, text
    (None when not editable) and reason (why it isn't editable).
    """
    params = {'ref': ref} if ref else {}
    data, error = github_api('GET', _contents_path(owner, repo, path), access_token, params=params)
    if error:
        return None, error
    if isinstance(data, list) or data.get('type') != 'file':
        return None, f"{path} is not a file."

    result = {'path': data.get('path', path), 'sha': data.get('sha'), 'size': data.get('size', 0),
              'html_url': data.get('html_url'), 'text': None, 'reason': None}
    if (data.get('size') or 0) > MAX_EDITABLE_BYTES or data.get('encoding') != 'base64':
        result['reason'] = "This file is larger than 1 MB, which is too big to edit in the browser."
        return result, None
    try:
        raw = base64.b64decode(data.get('content') or '')
    except (binascii.Error, ValueError):
        return None, "GitHub returned content that couldn't be decoded."
    result['text'] = decode_text(raw)
    if result['text'] is None:
        result['reason'] = "This looks like a binary file, so it can't be edited as text. Upload a replacement instead."
    return result, None


def prepare_text(submitted, original=None):
    """
    Browsers submit textarea content with CRLF line endings. Keep the file's own style:
    CRLF only if the original file used it, otherwise LF.
    """
    text = (submitted or '').replace('\r\n', '\n')
    if original is not None and '\r\n' in original:
        text = text.replace('\n', '\r\n')
    return text


# --- Committing --------------------------------------------------------------

def validate_target(form, branch_names):
    """
    Where to commit: the chosen existing branch, or a new branch created from it.
    Returns ({'branch', 'new_branch'}, error).
    """
    branch = (form.get('branch') or '').strip()
    if branch not in branch_names:
        return None, "Choose a branch to commit to."
    if form.get('target') != 'new':
        return {'branch': branch, 'new_branch': None}, None
    new_branch = (form.get('new_branch') or '').strip()
    if not valid_branch(new_branch):
        return None, "Enter a valid name for the new branch."
    if new_branch in branch_names:
        return None, f"A branch named {new_branch} already exists."
    return {'branch': branch, 'new_branch': new_branch}, None


def validate_message(message, default):
    message = (message or '').strip() or default
    if len(message) > MAX_MESSAGE_LENGTH:
        return None, f"The commit message can be at most {MAX_MESSAGE_LENGTH} characters."
    return message, None


def _current_blob_sha(owner, repo, path, commit_sha, access_token):
    """The blob SHA at path in a commit: (sha, None), (None, None) if absent, or (None, error)."""
    data, error = github_api('GET', _contents_path(owner, repo, path), access_token, params={'ref': commit_sha})
    if error == 'Not Found':
        return None, None
    if error:
        return None, error
    if isinstance(data, list) or data.get('type') != 'file':
        return None, f"{path} is a directory."
    return data.get('sha'), None


def commit_changes(owner, repo, target, changes, message, access_token):
    """
    Commit file changes in a single commit.
    `changes` is a list of {'path', 'content': bytes, 'expected_sha'} where expected_sha is the blob
    SHA the user started from, None for "must not exist yet", or MISSING to skip the check.
    `target` comes from validate_target. Returns (commit, error).
    """
    if not valid_names(owner, repo):
        return None, "Invalid repository name."
    if not changes:
        return None, "There are no changes to commit."
    repo_path = _repo_path(owner, repo)
    base_branch = target['branch']

    ref, error = github_api('GET', f'{repo_path}/git/ref/heads/{quote(base_branch, safe="/")}', access_token)
    if error:
        return None, f"Couldn't read branch {base_branch}: {error}"
    head_sha = ref['object']['sha']

    for change in changes:
        expected = change.get('expected_sha', MISSING)
        if expected is MISSING:
            continue
        current, error = _current_blob_sha(owner, repo, change['path'], head_sha, access_token)
        if error:
            return None, error
        if expected is None and current is not None:
            return None, f"{change['path']} already exists on {base_branch}."
        if expected is not None and current != expected:
            return None, (f"{change['path']} was changed on {base_branch} after you opened it. "
                          "Reload to get the latest version, then reapply your edit.")

    head_commit, error = github_api('GET', f'{repo_path}/git/commits/{head_sha}', access_token)
    if error:
        return None, error

    entries = []
    for change in changes:
        blob, error = github_api('POST', f'{repo_path}/git/blobs', access_token, json={
            'content': base64.b64encode(change['content']).decode('ascii'), 'encoding': 'base64'})
        if error:
            return None, f"Couldn't upload {change['path']}: {error}"
        entries.append({'path': change['path'], 'mode': FILE_MODE, 'type': 'blob', 'sha': blob['sha']})

    tree, error = github_api('POST', f'{repo_path}/git/trees', access_token,
                             json={'base_tree': head_commit['tree']['sha'], 'tree': entries})
    if error:
        return None, error
    commit, error = github_api('POST', f'{repo_path}/git/commits', access_token,
                               json={'message': message, 'tree': tree['sha'], 'parents': [head_sha]})
    if error:
        return None, error

    if target['new_branch']:
        _, error = github_api('POST', f'{repo_path}/git/refs', access_token,
                              json={'ref': f"refs/heads/{target['new_branch']}", 'sha': commit['sha']})
    else:
        # Not forced: if someone pushed meanwhile, GitHub refuses instead of overwriting their work.
        _, error = github_api('PATCH', f'{repo_path}/git/refs/heads/{quote(base_branch, safe="/")}', access_token,
                              json={'sha': commit['sha'], 'force': False})
    if error:
        if 'fast forward' in error.lower():
            error = f"{base_branch} was updated while you were committing. Try again."
        return None, f"Couldn't update the branch: {error}"
    return commit, None


def read_uploads(files, directory):
    """
    Turn uploaded files into commit changes under `directory`.
    Existing files are overwritten (expected_sha MISSING). Returns (changes, error).
    """
    files = [f for f in files if f and f.filename]
    if not files:
        return None, "Choose at least one file to upload."
    if len(files) > MAX_UPLOAD_FILES:
        return None, f"Upload at most {MAX_UPLOAD_FILES} files at a time."
    changes, seen = [], set()
    for uploaded in files:
        name = upload_name(uploaded.filename)
        if not name:
            return None, f"'{uploaded.filename}' isn't a valid file name."
        path = f'{directory}/{name}' if directory else name
        if normalize_path(path) is None:
            return None, f"'{path}' isn't a valid path."
        if path in seen:
            return None, f"{name} was selected twice."
        seen.add(path)
        changes.append({'path': path, 'content': uploaded.read(), 'expected_sha': MISSING})
    return changes, None
