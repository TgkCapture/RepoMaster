"""api_token_routes.py

Pages for the JSON API (issue #53): create and revoke API tokens for the current
account, and the interactive API documentation.
"""
from flask import flash, make_response, redirect, render_template, request, session, url_for

from app.routes import main_routes
from app.controllers.api_token_controller import MAX_NAME_LENGTH, create_token, list_tokens, revoke_token
from app.controllers.audit_controller import record_audit
from app.controllers.auth_controller import login_required


def _tokens_page(new_token=None, name='', status=200):
    response = make_response(render_template(
        'api_tokens.html', tokens=list_tokens(session['installation_id']), new_token=new_token,
        name=name, max_name_length=MAX_NAME_LENGTH, account=session.get('github_username')), status)
    # A new token is only ever on this one response; keep it out of caches
    response.headers['Cache-Control'] = 'no-store'
    return response


@main_routes.route('/api/tokens', methods=['GET'])
@login_required
def api_tokens():
    return _tokens_page()


@main_routes.route('/api/tokens', methods=['POST'])
@login_required
def create_api_token():
    account = session.get('github_username')
    if not account:
        flash("Your session doesn't say which account you're using. Please log in again.", 'danger')
        return redirect(url_for('main.api_tokens'))
    name = request.form.get('name', '')
    token, error = create_token(session['installation_id'], account, session.get('github_account_type'),
                                session.get('github_user_login'), name)
    if error:
        flash(error, 'danger')
        return _tokens_page(name=name, status=400)
    record_audit('api_token.create', None, True, 'Created', target=' '.join(name.split()))
    # Rendered directly (not redirected) so the token never goes into the session
    return _tokens_page(new_token=token)


@main_routes.route('/api/tokens/<int:token_id>/revoke', methods=['POST'])
@login_required
def revoke_api_token(token_id):
    tokens = {token['id']: token for token in list_tokens(session['installation_id'])}
    if revoke_token(token_id, session['installation_id']):
        record_audit('api_token.revoke', None, True, 'Revoked', target=tokens[token_id]['name'])
        flash(f"Token '{tokens[token_id]['name']}' revoked. Tools using it will stop working.", 'success')
    else:
        flash("That token doesn't exist or is already revoked.", 'warning')
    return redirect(url_for('main.api_tokens'))


@main_routes.route('/api/docs', methods=['GET'])
def api_docs():
    """Swagger UI for OpenAPI.json. Public: it only describes the API."""
    return render_template('api_docs.html')
