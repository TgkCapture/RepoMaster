"""auth_controller.py
"""
import os
import requests
from flask import Flask, Blueprint, render_template, redirect, url_for, session, request
from flask_oauthlib.client import OAuth
from werkzeug.urls import url_encode, url_unquote, url_quote

auth_controller = Blueprint('authorize', __name__)
auth_controller.secret_key = '123456'

oauth = OAuth(auth_controller)
github = oauth.remote_app(
    'github',
    consumer_key='',  
    consumer_secret='',  
    request_token_params={'scope': 'user:email'},
    base_url='https://api.github.com/',
    request_token_url=None,
    access_token_method='POST',
    access_token_url='https://github.com/login/oauth/access_token',
    authorize_url='https://github.com/login/oauth/authorize',
)

def index():
    return render_template('index.html')

def login():
    if 'github_token' in session:
        # If user is already logged in, redirect to index
        return redirect(url_for('index'))
    
    # Redirect user to GitHub authorization page
    return github.authorize(callback=url_for('main.authorized_route', _external=True))

def logout():
    session.pop('github_token', None)
    return redirect(url_for('index'))

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
    return redirect(url_for('index'))

def get_github_oauth_token():
    return session.get('github_token')