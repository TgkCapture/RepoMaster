"""auth_routes.py

Home page, sign-in with GitHub, GitHub App installation and logout.

Sign-in flow:
1. /login              -> redirect to GitHub with a one-time `state` value
2. /github/callback    -> verify `state`, exchange the code for a user token, then pick an
                          App installation *that this user can access* and start the session
3. /github/authorize   -> GitHub App "Setup URL". GitHub redirects here after the App is
                          installed. The installation_id in the URL is only a hint; it is
                          verified against the user's installations during sign-in.
"""
import logging
from flask import render_template, request, redirect, url_for, session, flash, current_app
from app.routes import main_routes
from app.controllers.auth_controller import (
    is_user_logged_in, clear_session, generate_oauth_state, validate_oauth_state,
    build_authorize_url, exchange_code_for_user_token, get_authenticated_user,
    get_user_installations, choose_installation, start_user_session, oauth_callback_url,
    OAUTH_PURPOSE_CREATE_REPOSITORY,
)
from app.routes.repo_creation_routes import finish_repository_creation

@main_routes.route('/')
def home():
    """
    Renders the home page.
    """
    return render_template('index.html', is_user_logged_in=is_user_logged_in)

@main_routes.route('/logout')
def logout():
    """
    Route to log out the user.
    """
    clear_session()
    flash("You have been logged out successfully.", "info")
    return redirect(url_for('main.home'))

@main_routes.route('/login', methods=['GET'])
def login():
    """
    Start signing in with GitHub.
    """
    if not current_app.config.get('GITHUB_CLIENT_ID'):
        logging.error("GITHUB_CLIENT_ID is not set in the environment.")
        return "Configuration error: GITHUB_CLIENT_ID is not defined.", 500

    state = generate_oauth_state()
    return redirect(build_authorize_url(state, oauth_callback_url()))

@main_routes.route('/github/callback', methods=['GET'])
def github_callback():
    """
    OAuth callback: verify the user and the installation they may use, then sign them in.
    """
    if request.args.get('error'):
        logging.warning(f"GitHub sign-in was not completed: {request.args.get('error')}")
        flash("GitHub sign-in was cancelled.", "info")
        return redirect(url_for('main.home'))

    purpose = validate_oauth_state(request.args.get('state'))
    if not purpose:
        logging.warning("OAuth callback with missing or invalid state.")
        return "Invalid or expired sign-in request. Please try signing in again.", 400

    code = request.args.get('code')
    if not code:
        return "Missing authorization code. Please try signing in again.", 400

    user_token = exchange_code_for_user_token(code, oauth_callback_url())
    if not user_token:
        return "Failed to sign in with GitHub. Please try again.", 500

    user = get_authenticated_user(user_token)

    if purpose == OAUTH_PURPOSE_CREATE_REPOSITORY:
        if user is None:
            return "Failed to load your GitHub account details. Please try again.", 500
        return finish_repository_creation(user, user_token)

    requested_installation_id = session.pop('pending_installation_id', None)
    installations = get_user_installations(user_token)
    if user is None or installations is None:
        return "Failed to load your GitHub account details. Please try again.", 500

    # Signing in again (e.g. to refresh the account list) keeps the account in use
    previous_installation_id = (session.get('installation_id')
                                if session.get('github_user_login') == user.get('login') else None)

    if not installations:
        flash("Install the RepoMaster GitHub App on your account to get started.", "info")
        return redirect(url_for('main.install_github_app'))

    installation = choose_installation(installations, user.get('login'), requested_installation_id,
                                       previous_installation_id)
    if installation is None:
        logging.warning(f"User '{user.get('login')}' requested installation {requested_installation_id} "
                        "which they cannot access.")
        return "That GitHub App installation is not available to your GitHub account.", 403

    start_user_session(user, installation, installations)
    flash(f"Signed in as {user.get('login')}.", "success")
    return redirect(url_for('main.home'))

@main_routes.route('/github/authorize', methods=['GET'])
def github_authorize():
    """
    GitHub App Setup URL: GitHub redirects here after the App is installed.
    The installation is not trusted from the URL; the user signs in and it is verified.
    """
    if request.args.get('setup_action') == 'request':
        # An organization member asked an owner to install the App; nothing to use yet.
        flash("Installation requested. You can sign in once an organization owner approves it.", "info")
        return redirect(url_for('main.home'))

    installation_id = request.args.get('installation_id')
    if installation_id:
        session['pending_installation_id'] = installation_id
        logging.info(f"Installation {installation_id} pending verification through sign-in.")

    return redirect(url_for('main.login'))

@main_routes.route('/github/install', methods=['GET'])
def install_github_app():
    """
    Redirect the user to the GitHub App installation page.
    """
    github_app_name = current_app.config.get('GITHUB_APP_NAME')
    if not github_app_name:
        logging.error("GITHUB_APP_NAME is not set in the environment.")
        return "Configuration error: GITHUB_APP_NAME is not defined.", 500

    installation_url = f"https://github.com/apps/{github_app_name}/installations/new"
    return redirect(installation_url)
