"""auth_controller.py
"""
import os
import requests
from flask import Blueprint, render_template, redirect, url_for, session, flash, request
from app.config.oauth_config import oauth

auth_controller = Blueprint('authorize', __name__)

def login():
    """Renders the login Page"""
    return render_template('login.html')

def github_authorization():
    """Redirects to GitHub for authorization"""
    redirect_uri = url_for('.login_success', _external=True) 
    return oauth.github.authorize_redirect(redirect_uri=redirect_uri)

# @github.tokengetter
def get_github_oauth_token():
    """Gets the GitHub access token stored in the session"""
    return session.get('github_token')

def login_success():
    """successful GitHub authorization"""
    resp = oauth.github.authorized_response()
    if resp is None or 'access_token' not in resp:
        flash('Authorization failed. Please try again.', 'danger')
        return redirect(url_for('main.index')) #TODO: Handle the redirect
    
    session['github_token'] = (resp['access_token'], '')
    flash('authorized in successfully!', 'success')
    return redirect(url_for('main.home'))

def logout():
    """Logs out the user by clearing the session"""
    session.pop('github_token', None)
    flash('Logged out successfully!', 'info')
    return redirect(url_for('main.index'))