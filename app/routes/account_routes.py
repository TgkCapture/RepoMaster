"""account_routes.py

Switch between the accounts and organizations where RepoMaster is installed (issue #50).
The list comes from GitHub at sign-in (installations the signed-in user can access);
switching only ever picks from that verified list.
"""
from flask import flash, redirect, render_template, request, session, url_for
from app.routes import main_routes
from app.controllers.auth_controller import (
    account_avatar_url, available_installations, is_user_logged_in, login_required, switch_installation,
)


@main_routes.app_context_processor
def account_switcher():
    """The active account for the navbar switcher (None when signed out)."""
    def current_account():
        if not is_user_logged_in():
            return None
        for entry in available_installations():
            if str(entry['id']) == str(session.get('installation_id')):
                return entry
        # Sessions from before the switcher existed only know the active account
        return {'id': session.get('installation_id'), 'login': session.get('github_username'),
                'type': session.get('github_account_type') or 'User', 'account_id': None}
    return {'current_account': current_account, 'account_avatar_url': account_avatar_url}


@main_routes.route('/accounts', methods=['GET'])
@login_required
def accounts():
    """Every account / organization the user can manage with RepoMaster."""
    return render_template('accounts.html', installations=available_installations(),
                           active_id=session.get('installation_id'))


@main_routes.route('/accounts/switch', methods=['POST'])
@login_required
def switch_account():
    """Make another verified installation the active one."""
    entry = switch_installation(request.form.get('installation_id', ''))
    if entry is None:
        flash("That account isn't available to you. Sign in again to refresh the list.", 'danger')
        return redirect(url_for('main.accounts'))
    flash(f"Now managing {entry['login']}.", 'success')
    return redirect(url_for('main.show_github_repositories'))
