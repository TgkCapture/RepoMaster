"""issues_controller.py
"""
import os
import logging
import requests
from flask import session
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token

def get_github_issues(repo_name):
    """Fetches GitHub issues within a repository."""
    
    username = session.get("username", "TgkCapture")  #TODO: Replace with dynamic fetching
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch GitHub issues.")
        return None

    url = f'https://api.github.com/repos/{username}/{repo_name}/issues'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
        issues = response.json()
        logging.info(f"Fetched {len(issues)} issues for repository {repo_name}.")
        return issues
    except RequestException as e:
        logging.error(f"Failed to fetch issues for repository {repo_name}: {e}")
        return None