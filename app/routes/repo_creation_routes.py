"""repo_creation_routes.py

Create repositories from a form (issue #38).

1. GET  /repositories/new         form
2. POST /repositories/new         validate, keep the request in the session and send the user
                                  through GitHub OAuth for a user token (no prompt if the App is
                                  already authorized)
3. GET  /github/callback          (auth_routes) calls finish_repository_creation() with that token
4. GET  /repositories/new/result  shows what was created
"""
import logging
from flask import render_template, request, redirect, url_for, session, flash
from app.routes import main_routes
from app.controllers.auth_controller import (
    get_installation_access_token, login_required, is_user_logged_in,
    generate_oauth_state, build_authorize_url, oauth_callback_url, OAUTH_PURPOSE_CREATE_REPOSITORY,
)
from app.controllers.repo_controller import get_github_repositories
from app.controllers.repo_creation_controller import (
    get_form_options, validate_new_repository, create_repository,
)

def _installation_settings_url():
    owner = session.get('github_username')
    installation_id = session.get('installation_id')
    if session.get('github_account_type') == 'Organization':
        return f"https://github.com/organizations/{owner}/settings/installations/{installation_id}"
    return f"https://github.com/settings/installations/{installation_id}"

def _form_context(access_token):
    """Option lists for the form, or None if repositories can't be loaded."""
    repositories = get_github_repositories(access_token)
    if repositories is None:
        return None
    full_names = sorted((r['full_name'] for r in repositories), key=str.lower)
    return {
        'templates': [r['full_name'] for r in sorted(repositories, key=lambda r: r['full_name'].lower())
                      if r.get('is_template')],
        'label_sources': full_names,
        **get_form_options(access_token),
    }

def _render_form(context, values=None, error=None, status=200):
    return render_template('new_repository.html', values=values or {}, error=error,
                           owner=session.get('github_username'), **context), status

@main_routes.route('/repositories/new', methods=['GET', 'POST'])
@login_required
def new_repository():
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500

    context = _form_context(access_token)
    if context is None:
        return "Failed to fetch repositories from GitHub", 500

    if request.method == 'GET':
        return _render_form(context)

    spec, error = validate_new_repository(
        request.form,
        owner=session.get('github_username'),
        owner_type=session.get('github_account_type'),
        user_login=session.get('github_user_login'),
        templates=context['templates'],
        label_sources=context['label_sources'],
        options={'gitignore_templates': context['gitignore_templates'], 'licenses': context['licenses']},
    )
    if error:
        return _render_form(context, values=request.form, error=error, status=400)

    session['pending_repository'] = spec
    state = generate_oauth_state(OAUTH_PURPOSE_CREATE_REPOSITORY)
    logging.info(f"Repository creation of {spec['owner']}/{spec['name']} pending user authorization.")
    return redirect(build_authorize_url(state, oauth_callback_url()))

def finish_repository_creation(user, user_token):
    """
    Called from the OAuth callback once GitHub has returned a user token for a pending creation.
    The token is used for this request only.
    """
    spec = session.pop('pending_repository', None)
    if not spec:
        flash("That repository request expired. Please submit the form again.", "danger")
        return redirect(url_for('main.new_repository'))

    if not is_user_logged_in() or user.get('login') != session.get('github_user_login'):
        logging.warning(f"GitHub user '{user.get('login')}' does not match the signed-in RepoMaster user.")
        return "The GitHub account that authorized this doesn't match the one signed in to RepoMaster.", 403

    session['repository_creation_result'] = create_repository(spec, user_token)
    return redirect(url_for('main.new_repository_result'))

@main_routes.route('/repositories/new/result', methods=['GET'])
@login_required
def new_repository_result():
    result = session.pop('repository_creation_result', None)
    if not result:
        return redirect(url_for('main.new_repository'))
    return render_template('new_repository_result.html', result=result,
                           installation_settings_url=_installation_settings_url())
