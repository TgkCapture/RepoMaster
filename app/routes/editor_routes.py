"""editor_routes.py

In-browser file editor and file uploads (issue #42).
"""
import logging
import posixpath
from flask import flash, redirect, render_template, request, session, url_for
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.branch_management_controller import valid_names
from app.controllers.repo_controller import get_repository, list_branches
from app.controllers.file_editor_controller import (
    MAX_UPLOAD_BYTES, MAX_UPLOAD_FILES, MISSING,
    commit_changes, editor_mode, is_markdown, load_file, normalize_directory, normalize_path,
    prepare_text, read_uploads, validate_message, validate_target,
)


def _branch_context(owner, repo, access_token):
    """Returns (branch names, default branch, None) or (None, None, error)."""
    branches, error = list_branches(owner, repo, access_token)
    if error:
        return None, None, error
    repository, _ = get_repository(owner, repo, access_token)
    return [b['name'] for b in branches], (repository or {}).get('default_branch'), None


def _after_commit(owner, repo, target, path_for_listing):
    """Where to go after a successful commit: the new pull request form for a new branch, else the folder."""
    if target['new_branch'] and request.form.get('open_pr') == 'on' and owner == session.get('github_username'):
        return redirect(url_for('main.manage_pull_requests', repo_name=repo, create=1,
                                base=target['branch'], head=target['new_branch']))
    branch = target['new_branch'] or target['branch']
    return redirect(url_for('main.get_contents', owner=owner, repo=repo,
                            path=path_for_listing or None, branch=branch))


@main_routes.route('/github/repos/<owner>/<repo>/edit', methods=['GET', 'POST'])
@login_required
def edit_file(owner, repo):
    """
    GET ?path=...&branch=...: open a file in the editor (no path: a new file, ?dir= sets its folder).
    POST: commit the edited file to the chosen branch or a new one.
    """
    if not valid_names(owner, repo):
        return "Invalid repository name", 400
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    branch_names, default_branch, error = _branch_context(owner, repo, access_token)
    if error:
        return f"Failed to fetch branches: {error}", 500

    original_path = request.values.get('original_path') if request.method == 'POST' else request.args.get('path')
    branch = request.values.get('branch') or default_branch
    if branch not in branch_names:
        branch = default_branch

    file_info = None
    if original_path:
        original_path = normalize_path(original_path)
        if original_path is None:
            return "Invalid file path", 400
        file_info, error = load_file(owner, repo, original_path, branch, access_token)
        if error:
            status = 404 if error == 'Not Found' else 400 if error.endswith('is not a file.') else 500
            return f"Couldn't open the file: {error}", status

    context = {
        'owner': owner, 'repo': repo, 'branches': branch_names, 'branch': branch, 'file': file_info,
        'directory': normalize_directory(request.args.get('dir')) or '',
        'session_owner': session.get('github_username'),
    }

    if request.method == 'GET':
        if file_info and file_info['text'] is None:
            return render_template('file_editor.html', **context, text=None, mode_scripts=[], mode='text/plain',
                                   markdown=False, form={})
        path = file_info['path'] if file_info else ''
        scripts, mode = editor_mode(path)
        return render_template('file_editor.html', **context, text=file_info['text'] if file_info else '',
                               mode_scripts=scripts, mode=mode, markdown=is_markdown(path) or not file_info,
                               form={})

    # --- POST: commit ---
    def fail(message):
        flash(message, 'error')
        path = (file_info or {}).get('path', '') or request.form.get('path', '')
        scripts, mode = editor_mode(path)
        return render_template('file_editor.html', **context, text=request.form.get('content', ''),
                               mode_scripts=scripts, mode=mode, markdown=is_markdown(path) or not file_info,
                               form=request.form), 400

    if file_info and file_info['text'] is None:
        return fail("This file can't be edited as text.")
    target, error = validate_target(request.form, branch_names)
    if error:
        return fail(error)

    if file_info:
        path = file_info['path']
        expected_sha = request.form.get('sha') or file_info['sha']
        text = prepare_text(request.form.get('content'), file_info['text'])
        if text == file_info['text'] and not target['new_branch'] and expected_sha == file_info['sha']:
            flash("No changes to commit.", 'info')
            return redirect(url_for('main.edit_file', owner=owner, repo=repo, path=path, branch=branch))
        default_message = f"Update {posixpath.basename(path)}"
    else:
        path = normalize_path(request.form.get('path'))
        if path is None:
            return fail("Enter a valid file path, e.g. docs/notes.md.")
        expected_sha = None  # a new file must not exist yet
        text = prepare_text(request.form.get('content'))
        default_message = f"Create {posixpath.basename(path)}"

    message, error = validate_message(request.form.get('message'), default_message)
    if error:
        return fail(error)

    commit, error = commit_changes(owner, repo, target, [
        {'path': path, 'content': text.encode('utf-8'), 'expected_sha': expected_sha}], message, access_token)
    if error:
        logging.warning(f"Commit of {path} to {owner}/{repo} failed: {error}")
        return fail(error)

    where = target['new_branch'] or target['branch']
    flash(f"Committed {path} to {where} ({commit['sha'][:7]}).", 'success')
    return _after_commit(owner, repo, target, posixpath.dirname(path))


@main_routes.route('/github/repos/<owner>/<repo>/upload', methods=['GET', 'POST'])
@login_required
def upload_files(owner, repo):
    """Upload one or more files (text or binary) into a folder, as a single commit."""
    if not valid_names(owner, repo):
        return "Invalid repository name", 400
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    branch_names, default_branch, error = _branch_context(owner, repo, access_token)
    if error:
        return f"Failed to fetch branches: {error}", 500
    branch = request.values.get('branch') or default_branch
    if branch not in branch_names:
        branch = default_branch
    directory = normalize_directory(request.values.get('dir'))

    context = {'owner': owner, 'repo': repo, 'branches': branch_names, 'branch': branch,
               'directory': directory or '', 'max_files': MAX_UPLOAD_FILES,
               'max_megabytes': MAX_UPLOAD_BYTES // (1024 * 1024), 'session_owner': session.get('github_username')}
    if request.method == 'GET':
        return render_template('upload_files.html', **context, form={})

    def fail(message):
        flash(message, 'error')
        return render_template('upload_files.html', **context, form=request.form), 400

    if directory is None:
        return fail("Enter a valid folder, or leave it empty for the repository root.")
    target, error = validate_target(request.form, branch_names)
    if error:
        return fail(error)
    changes, error = read_uploads(request.files.getlist('files'), directory)
    if error:
        return fail(error)
    names = ', '.join(posixpath.basename(c['path']) for c in changes)
    message, error = validate_message(request.form.get('message'), f"Upload {names}"[:200])
    if error:
        return fail(error)

    commit, error = commit_changes(owner, repo, target, changes, message, access_token)
    if error:
        logging.warning(f"Upload to {owner}/{repo} failed: {error}")
        return fail(error)

    where = target['new_branch'] or target['branch']
    count = len(changes)
    flash(f"Uploaded {count} file{'s' if count != 1 else ''} to {where} ({commit['sha'][:7]}).", 'success')
    return _after_commit(owner, repo, target, directory)


@main_routes.app_errorhandler(413)
def request_too_large(error):
    return (f"That upload is too large. The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB per upload.", 413)
