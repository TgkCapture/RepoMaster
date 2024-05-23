"""auth_controller.py
"""

import requests
import logging
from flask import Blueprint, render_template, url_for, session, request, redirect
from app.config.oauth_config import github

auth_controller = Blueprint('authorize', __name__)
auth_controller.secret_key = '123456'

def index():
    return render_template('index.html')

def login():
    if 'github_token' in session:
    
        return render_template('dashboard.html', get_github_oauth_token=get_github_oauth_token)
    
    # Redirect user to GitHub authorization page
    return github.authorize(callback=url_for('main.authorized_route', _external=True))

def logout():
    if 'github_token' in session:
        session.pop('github_token')
        return redirect(url_for('main.home'))
    else:
        return "You are already logged out."

def authorized():
    error_reason = request.args.get('error_reason')
    if error_reason:
        error_message = f"Access denied: reason={error_reason}"
        logging.error(error_message)
        return render_template('error.html', error_message=error_message)
    
    resp = github.authorized_response()
    if resp is None or resp.get('access_token') is None:
        error_description = request.args.get('error_description', '')
        error_message = f"Access denied: reason={error_description}"
        logging.error(error_message)
        return render_template('error.html', error_message=error_message)
    
    session['github_token'] = (resp['access_token'], '')
    
    return render_template('dashboard.html', get_github_oauth_token=get_github_oauth_token)

def get_github_oauth_token():
    return session.get('github_token')

def get_user_info():
    github_token = get_github_oauth_token()
    if not github_token:
        return None

    headers = {'Authorization': f'token {github_token[0]}'}
    response = requests.get('https://api.github.com/user', headers=headers)

    if response.status_code == 200:
        user_data = response.json()
        return user_data.get('login'), user_data.get('id')
    else:
        logging.error(f"Error retrieving user info: {response.status_code}")
        return None

def is_user_logged_in():
    """
    Checks if a user is logged in.
    """
    return 'github_token' in session and session.get('github_token') is not None