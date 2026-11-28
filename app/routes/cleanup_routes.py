"""cleanup_routes.py

Cleanup dashboard (issue #36): repositories that look inactive, empty or unmodified forks,
plus per-repository review of merged and stale branches.
Archive/delete of repositories goes through the bulk actions confirm/apply flow.
"""
import logging
from flask import render_template, request, redirect, url_for, flash
from app.routes import main_routes
from app.controllers.audit_controller import record_audit
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.repo_controller import get_github_repositories, list_branches, get_repository, delete_branch_ref
from app.controllers.bulk_controller import REPO_FULL_NAME_PATTERN
from app.controllers.cleanup_controller import (
    parse_months, analyze_repositories, find_unmodified_forks, analyze_branches,
)

def _parse_repo(full_name):
    """Split 'owner/name' into (owner, name), or return None if it isn't a valid full name."""
    full_name = (full_name or '').strip()
    if not REPO_FULL_NAME_PATTERN.match(full_name):
        return None
    return tuple(full_name.split('/', 1))

@main_routes.route('/repositories/cleanup', methods=['GET'])
@login_required
def cleanup_dashboard():
    months = parse_months(request.args.get('months'))

    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    repositories = get_github_repositories(access_token)
    if repositories is None:
        return "Failed to fetch repositories from GitHub", 500

    analysis = analyze_repositories(repositories, months)
    unmodified_forks, unchecked_forks = find_unmodified_forks(analysis['forks'], access_token)
    reviewable = sorted((r for r in repositories if not r.get('archived')), key=lambda r: r['full_name'].lower())

    return render_template(
        'cleanup.html',
        months=months,
        inactive=analysis['inactive'],
        empty=analysis['empty'],
        unmodified_forks=unmodified_forks,
        unchecked_forks=unchecked_forks,
        archived_count=analysis['archived_count'],
        total=len(repositories),
        reviewable=reviewable,
    )

@main_routes.route('/repositories/cleanup/branches', methods=['GET'])
@login_required
def cleanup_branches():
    months = parse_months(request.args.get('months'))
    repo = _parse_repo(request.args.get('repo'))
    if not repo:
        flash("Choose a repository to review.", "danger")
        return redirect(url_for('main.cleanup_dashboard', months=months))
    owner, name = repo

    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    result, error = analyze_branches(owner, name, access_token, months)
    if error:
        flash(f"Could not review branches of {owner}/{name}: {error}", "danger")
        return redirect(url_for('main.cleanup_dashboard', months=months))

    return render_template('cleanup_branches.html', full_name=f"{owner}/{name}", months=months, **result)

@main_routes.route('/repositories/cleanup/branches/delete', methods=['POST'])
@login_required
def cleanup_delete_branches():
    months = parse_months(request.form.get('months'))
    repo = _parse_repo(request.form.get('repo'))
    if not repo:
        flash("Invalid repository.", "danger")
        return redirect(url_for('main.cleanup_dashboard', months=months))
    owner, name = repo
    back = redirect(url_for('main.cleanup_branches', repo=f"{owner}/{name}", months=months))

    requested = []
    for branch in request.form.getlist('branches'):
        if branch and branch not in requested:
            requested.append(branch)
    if not requested:
        flash("Select at least one branch to delete.", "danger")
        return back

    access_token = get_installation_access_token()
    if not access_token:
        flash("Failed to authenticate with GitHub.", "danger")
        return back

    # Re-check against GitHub: never delete the default branch or a protected branch
    details, error = get_repository(owner, name, access_token)
    if not error:
        branches, error = list_branches(owner, name, access_token)
    if error:
        flash(f"Could not load branches of {owner}/{name}: {error}", "danger")
        return back
    existing = {b['name']: b for b in branches}

    deleted, failed = [], []
    for branch in requested:
        if branch == details['default_branch']:
            failed.append(f"{branch} (default branch)")
        elif branch not in existing:
            failed.append(f"{branch} (not found)")
        elif existing[branch].get('protected'):
            failed.append(f"{branch} (protected)")
        else:
            ok, error = delete_branch_ref(owner, name, branch, access_token)
            record_audit('branch.delete', f'{owner}/{name}', ok, error or 'Deleted (cleanup)', target=branch)
            if ok:
                deleted.append(branch)
            else:
                failed.append(f"{branch} ({error})")

    logging.info(f"Branch cleanup on {owner}/{name}: deleted {len(deleted)}, failed {len(failed)}.")
    if deleted:
        flash(f"Deleted {len(deleted)} branch(es): {', '.join(deleted)}", "success")
    if failed:
        flash(f"Not deleted: {', '.join(failed)}", "danger")
    return back
