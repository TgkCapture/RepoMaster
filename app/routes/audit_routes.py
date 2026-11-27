"""audit_routes.py

Audit log and scheduled (soft) repository deletions (issue #51).
"""
from flask import flash, redirect, render_template, request, session, url_for
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.audit_controller import AUDIT_ACTIONS, PER_PAGE, RESULTS, list_audit_entries, parse_audit_filters
from app.controllers.soft_delete_controller import cancel_deletion, list_deletions, soft_delete_days


@main_routes.route('/audit', methods=['GET'])
@login_required
def audit_log():
    """Every destructive action taken through RepoMaster on the current account, newest first."""
    filters, warnings = parse_audit_filters(request.args)
    entries, total = list_audit_entries(session['installation_id'], filters)
    link_args = {key: value for key, value in filters.items() if key != 'page' and value}
    return render_template('audit.html', entries=entries, total=total, filters=filters, warnings=warnings,
                           link_args=link_args, actions=AUDIT_ACTIONS, results=RESULTS,
                           has_next=filters['page'] * PER_PAGE < total)


@main_routes.route('/deletions', methods=['GET'])
@login_required
def scheduled_deletions():
    """Repositories waiting to be deleted, with Undo, and recently finished deletions."""
    return render_template('deletions.html', deletions=list_deletions(session['installation_id']),
                           days=soft_delete_days())


@main_routes.route('/deletions/<int:deletion_id>/undo', methods=['POST'])
@login_required
def undo_deletion(deletion_id):
    """Cancel a scheduled deletion and unarchive the repository."""
    access_token = get_installation_access_token()
    if not access_token:
        flash("Failed to authenticate with GitHub.", 'danger')
        return redirect(url_for('main.scheduled_deletions'))
    ok, message = cancel_deletion(deletion_id, session['installation_id'], access_token)
    flash(message, 'success' if ok else 'danger')
    return redirect(url_for('main.scheduled_deletions'))
