"""
github_controller.py
"""
import os
import requests
from flask import Blueprint, session, render_template

github_controller = Blueprint('github', __name__)

GITHUB_API_URL = "https://api.github.com"

def get_github_repositories():
    """Fetches repositories from GitHub API using access token"""
    token = session.get("github_token")

    if not token:
        return None, "Access token not found. Please log in first."

    headers = {"Authorization": f"token {token}"}
    response = requests.get(f"{GITHUB_API_URL}/user/repos", headers=headers)

    if response.status_code == 200:
        return response.json(), None
    else:
        return None, f"Failed to fetch repositories: {response.json().get('message', 'Unknown error')}"
