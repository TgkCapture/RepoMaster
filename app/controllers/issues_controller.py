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
    
    username = session.get('github_username') 
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

def create_github_issue(repo_name, title, body=None):
    """Creates a new GitHub issue."""
    username = session.get('github_username')  
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot create GitHub issues.")
        return None

    url = f'https://api.github.com/repos/{username}/{repo_name}/issues'
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {"title": title, "body": body}

    try:
        response = requests.post(url, json=data, headers=headers, timeout=60)
        response.raise_for_status()
        issue = response.json()
        logging.info(f"Issue created successfully in repository {repo_name}.")
        return issue
    except RequestException as e:
        logging.error(f"Failed to create issue in repository {repo_name}: {e}")
        return None

def close_github_issue(repo_name, issue_number):
    """Closes an existing GitHub issue."""
    username = session.get('github_username')
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot close GitHub issues.")
        return None

    url = f'https://api.github.com/repos/{username}/{repo_name}/issues/{issue_number}'
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {"state": "closed"}

    try:
        response = requests.patch(url, json=data, headers=headers, timeout=60)
        response.raise_for_status()
        closed_issue = response.json()
        logging.info(f"Issue #{issue_number} successfully closed in repository {repo_name}.")
        return closed_issue
    except RequestException as e:
        logging.error(f"Failed to close issue #{issue_number} in repository {repo_name}: {e}")
        return None