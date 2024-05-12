"""auth_controller.py
"""

import requests
from flask import Blueprint, render_template, url_for, session, request
from app.config.oauth_config import github

auth_controller = Blueprint('authorize', __name__)
auth_controller.secret_key = '123456'

def index():
    return render_template('index.html')

def login():
    if 'github_token' in session:
        # If user is already logged in, redirect to index
        # return redirect(url_for('main.home'))
        return f"You are now signed in."
    
    # Redirect user to GitHub authorization page
    return github.authorize(callback=url_for('main.authorized_route', _external=True))

def logout():
    session.pop('github_token', None)
    # return redirect(url_for('main.home'))
    return f"You have now logged out"

def authorized():
    error_reason = request.args.get('error_reason')
    if error_reason:
        error_message = f"Access denied: reason={error_reason}"
        return render_template('error.html', error_message=error_message)
    
    resp = github.authorized_response()
    if resp is None or resp.get('access_token') is None:
        error_description = request.args.get('error_description', '')
        error_message = f"Access denied: reason={error_description}"
        return render_template('error.html', error_message=error_message)
    
    session['github_token'] = (resp['access_token'], '')
    # return redirect(url_for('main.home'))
    return f"You are now signed in.."

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
        print(f"Error retrieving user info: {response.status_code}")
        return None

def is_user_logged_in():
    """
    Checks if a user is logged in.
    """
    return 'github_token' in session and session.get('github_token') is not None