"""release_routes.py

Releases, tags and release assets (issue #43).
"""
import logging
from flask import flash, redirect, render_template, request, url_for
from app.routes import main_routes
from app.controllers.audit_controller import record_audit
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.branch_management_controller import valid_names
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago
from app.controllers.repo_controller import get_repository, list_branches
from app.controllers.releases_controller import (
    MAKE_LATEST, MAX_ASSETS_PER_UPLOAD,
    create_release, delete_asset, delete_release, generate_notes, get_release, human_size, list_releases,
    list_tags, tags_without_release, update_release, upload_assets, validate_release_form,
)


def _start(owner, repo):
    """(access_token, None) or (None, error_response) after the common checks."""
    if not valid_names(owner, repo):
        return None, ("Invalid repository name", 400)
    access_token = get_installation_access_token()
    if not access_token:
        return None, ("Failed to authenticate with GitHub", 500)
    return access_token, None


def _load_release(owner, repo, release_id, access_token):
    """(release, None) or (None, error_response)."""
    release, error = get_release(owner, repo, release_id, access_token)
    if error:
        return None, (f"Failed to fetch the release: {error}", 404 if error == 'Not Found' else 500)
    return release, None


def _release_url(owner, repo, release_id):
    return url_for('main.release_detail', owner=owner, repo=repo, release_id=release_id)


@main_routes.route('/repos/<owner>/<repo>/releases', methods=['GET'])
@login_required
def releases(owner, repo):
    """Releases (drafts included) and tags that have no release."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    release_list, error = list_releases(owner, repo, access_token)
    if error:
        return f"Failed to fetch releases: {error}", 500
    tags, error = list_tags(owner, repo, access_token)
    if error:
        flash(f"Couldn't load tags: {error}", 'error')
        tags = []
    for release in release_list:
        release['ago'] = time_ago(parse_github_date(release.get('published_at') or release.get('created_at')))
    return render_template('releases.html', owner=owner, repo=repo, releases=release_list,
                           loose_tags=tags_without_release(tags, release_list))


def _render_form(owner, repo, access_token, release=None, form=None, status=200):
    branches, error = list_branches(owner, repo, access_token)
    branch_names = [b['name'] for b in branches or []]
    if error:
        flash(f"Couldn't load branches: {error}", 'error')
    repository, _ = get_repository(owner, repo, access_token)
    tags, _ = list_tags(owner, repo, access_token)
    values = dict(form or {})
    if not form:
        values = {
            'tag_name': (release or {}).get('tag_name', ''),
            'target_commitish': (release or {}).get('target_commitish') or (repository or {}).get('default_branch', ''),
            'name': (release or {}).get('name') or '',
            'body': (release or {}).get('body') or '',
            'draft': 'on' if (release or {}).get('draft') else '',
            'prerelease': 'on' if (release or {}).get('prerelease') else '',
            'make_latest': 'legacy',
        }
    return render_template('release_form.html', owner=owner, repo=repo, release=release, values=values,
                           branches=branch_names, tags=[t['name'] for t in tags or []],
                           make_latest_options=MAKE_LATEST), status


def _save(owner, repo, access_token, release=None):
    """Handle a POST from the create / edit form (generate notes, or save)."""
    if request.form.get('action') == 'generate':
        notes, error = generate_notes(owner, repo, request.form, access_token)
        form = request.form.to_dict()
        if error:
            flash(f"Couldn't generate release notes: {error}", 'error')
        else:
            form['body'] = notes
            flash("Release notes generated. Review them, then save.", 'info')
        return _render_form(owner, repo, access_token, release, form)

    branches, error = list_branches(owner, repo, access_token)
    if error:
        flash(f"Couldn't load branches: {error}", 'error')
        return _render_form(owner, repo, access_token, release, request.form.to_dict(), 400)
    payload, error = validate_release_form(request.form, [b['name'] for b in branches])
    if not error:
        if release:
            saved, error = update_release(owner, repo, release['id'], payload, access_token)
        else:
            saved, error = create_release(owner, repo, payload, access_token)
    if error:
        logging.warning(f"Saving release in {owner}/{repo} failed: {error}")
        flash(f"Couldn't save the release: {error}", 'error')
        return _render_form(owner, repo, access_token, release, request.form.to_dict(), 400)
    flash(f"Release {saved.get('name') or saved.get('tag_name')} {'updated' if release else 'created'}.", 'success')
    return redirect(_release_url(owner, repo, saved['id']))


@main_routes.route('/repos/<owner>/<repo>/releases/new', methods=['GET', 'POST'])
@login_required
def new_release(owner, repo):
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    if request.method == 'GET':
        form = {'tag_name': request.args['tag']} if request.args.get('tag') else None
        if form:
            form.update(make_latest='legacy', name='', body='', target_commitish='')
        return _render_form(owner, repo, access_token, form=form)
    return _save(owner, repo, access_token)


@main_routes.route('/repos/<owner>/<repo>/releases/<int:release_id>', methods=['GET'])
@login_required
def release_detail(owner, repo, release_id):
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    release, failure = _load_release(owner, repo, release_id, access_token)
    if failure:
        return failure
    release['ago'] = time_ago(parse_github_date(release.get('published_at') or release.get('created_at')))
    for asset in release.get('assets') or []:
        asset['size_text'] = human_size(asset.get('size'))
    return render_template('release_detail.html', owner=owner, repo=repo, release=release,
                           max_assets=MAX_ASSETS_PER_UPLOAD)


@main_routes.route('/repos/<owner>/<repo>/releases/<int:release_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_release(owner, repo, release_id):
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    release, failure = _load_release(owner, repo, release_id, access_token)
    if failure:
        return failure
    if request.method == 'GET':
        return _render_form(owner, repo, access_token, release)
    return _save(owner, repo, access_token, release)


@main_routes.route('/repos/<owner>/<repo>/releases/<int:release_id>/delete', methods=['POST'])
@login_required
def delete_release_route(owner, repo, release_id):
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    release, failure = _load_release(owner, repo, release_id, access_token)
    if failure:
        return failure
    messages, error = delete_release(owner, repo, release, request.form.get('delete_tag') == 'on', access_token)
    record_audit('release.delete', f'{owner}/{repo}', error is None,
                 error or '; '.join(message for _, message in messages), target=release.get('tag_name'))
    if error:
        flash(f"Couldn't delete the release: {error}", 'error')
        return redirect(_release_url(owner, repo, release_id))
    for category, message in messages:
        flash(message, category)
    return redirect(url_for('main.releases', owner=owner, repo=repo))


@main_routes.route('/repos/<owner>/<repo>/releases/<int:release_id>/assets', methods=['POST'])
@login_required
def upload_release_assets(owner, repo, release_id):
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    release, failure = _load_release(owner, repo, release_id, access_token)
    if failure:
        return failure
    for category, message in upload_assets(owner, repo, release, request.files.getlist('assets'), access_token):
        flash(message, category)
    return redirect(_release_url(owner, repo, release_id))


@main_routes.route('/repos/<owner>/<repo>/releases/<int:release_id>/assets/<int:asset_id>/delete', methods=['POST'])
@login_required
def delete_release_asset(owner, repo, release_id, asset_id):
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    release, failure = _load_release(owner, repo, release_id, access_token)
    if failure:
        return failure
    name, error = delete_asset(owner, repo, release, asset_id, access_token)
    record_audit('release.asset_delete', f'{owner}/{repo}', error is None, error or 'Deleted',
                 target=name or str(asset_id))
    flash(f"Deleted {name}." if not error else f"Couldn't delete the file: {error}", 'success' if not error else 'error')
    return redirect(_release_url(owner, repo, release_id))
