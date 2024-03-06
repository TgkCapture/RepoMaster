"""auth_controller.py
"""
import os
import requests
from flask import Blueprint, render_template, redirect, url_for, session, flash, request
from flask_dance.contrib.github import github
from app.config.oauth_config import oauth


auth_controller = Blueprint('authorize', __name__)

def login():
    """Renders the login Page"""
    return render_template('login.html')

def github_authorization():
    """Redirects to GitHub for authorization"""
    return render_template('')

def login_success():
    """Successful GitHub authorization"""
    resp = github.get('/user')
    if not resp.ok:
        flash('Authorization failed. Please try again.', 'danger')
        return redirect(url_for('main.index')) #TODO: Handle the redirect

    flash('authorized in successfully!', 'success')
    return redirect(url_for('main.home'))

def logout():
    """Logs out the user by clearing the session"""
    session.pop('github_token', None)
    flash('Logged out successfully!', 'info')
    return redirect(url_for('main.index'))