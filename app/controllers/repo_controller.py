"""repo_controller.py
"""
import requests
import logging
import base64
from urllib.parse import quote
from requests.exceptions import RequestException
from app.controllers.auth_controller import get_installation_access_token

REQUEST_TIMEOUT = 60  # seconds

def _error_details(e):
    """Return GitHub's response body for a failed request, if there is one."""
    response = getattr(e, 'response', None)
    return response.text if response is not None else str(e)

MAX_REPOSITORY_PAGES = 10  # 100 repositories per page

def get_github_repositories(access_token):
    """
    Fetches the repositories the GitHub App installation has access to
    (including private ones), following pages up to MAX_REPOSITORY_PAGES.
    """
    url = 'https://api.github.com/installation/repositories'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        repositories = []
        for page in range(1, MAX_REPOSITORY_PAGES + 1):
            response = requests.get(url, headers=headers, params={'per_page': 100, 'page': page},
                                    timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()
            batch = data.get('repositories', [])
            repositories.extend(batch)
            if len(batch) < 100 or len(repositories) >= data.get('total_count', 0):
                break

        for repo in repositories:
            repo['language_color'] = get_language_color(repo['language'])

        return repositories
    except RequestException as e:
        logging.error(f"Failed to fetch repositories: {e}")
        return None

def get_language_color(language):
    """
    Get the color associated with a programming language.
    """
    language_colors = {
        "Python": "#3572A5",
        "JavaScript": "#f1e05a",
        "Java": "#b07219",
        "Go": "#00ADD8",
        "C++": "#f34b7d",
        "C": "#555555",
        "Ruby": "#701516",
        "PHP": "#4F5D95",
        "Swift": "#ffac45",
        "TypeScript": "#3178C6",
        "Kotlin": "#A97BFF",
        "HTML": "#e34c26",
        "CSS": "#563d7c"
    }
    return language_colors.get(language, "#cccccc")

def get_branches(owner, repo_name):
    """Fetches all branches of a repository."""
    access_token = get_installation_access_token()

    if not access_token:
        logging.error("Access token is missing. Cannot fetch branches.")
        return None

    headers = {'Authorization': f'Bearer {access_token}'}
    api_url = f'https://api.github.com/repos/{owner}/{repo_name}/branches'

    try:
        response = requests.get(api_url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        branches = response.json()
        return [branch['name'] for branch in branches]
    except RequestException as e:
        logging.error(f"Failed to fetch branches for repository {repo_name}: {e}")
        return None

def create_branch(owner, repo, access_token, ref_name, sha):
    """
    Create a new branch in the specified repository.
    """
    url = f'https://api.github.com/repos/{owner}/{repo}/git/refs'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    payload = {
        "ref": f"refs/heads/{ref_name}",
        "sha": sha
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except RequestException as e:
        logging.error(f"Failed to create branch '{ref_name}' in repository '{owner}/{repo}': {_error_details(e)}")
        return None

def get_default_branch_sha(owner, repo, access_token):
    url = f'https://api.github.com/repos/{owner}/{repo}'
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        repo_data = response.json()
        default_branch = repo_data['default_branch']

        branch_url = f'https://api.github.com/repos/{owner}/{repo}/git/refs/heads/{default_branch}'
        branch_response = requests.get(branch_url, headers=headers, timeout=REQUEST_TIMEOUT)
        branch_response.raise_for_status()
        branch_data = branch_response.json()
        return branch_data['object']['sha']
    except RequestException as e:
        logging.error(f"Failed to get default branch SHA for repository '{owner}/{repo}': {e}")
        return None

def get_branch_details(owner, repo_name, branch_name):
    """
    Fetch details about a specific branch in the repository.
    Returns (branch_details, error_message).
    """
    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to authenticate with GitHub.")
        return None, "Authentication failed"

    url = f"https://api.github.com/repos/{owner}/{repo_name}/branches/{branch_name}"
    headers = {'Authorization': f'Bearer {access_token}'}

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        branch_details = response.json()
        logging.info(f"Branch details fetched successfully for '{owner}/{repo_name}:{branch_name}'.")
        return branch_details, None
    except RequestException as e:
        logging.error(f"Failed to fetch details for branch '{branch_name}' in repository '{owner}/{repo_name}': {e}")
        return None, f"Failed to fetch details for branch '{branch_name}'"

def get_repository_contents(owner, repo, path, branch=None):
    """
    Retrieve the contents of a file or directory.
    A directory returns a list of entries; a file returns a single dict.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}

    params = {"ref": branch} if branch else {}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch repository contents: {e}")
        return None

def create_file(owner, repo, file_name, content, message, branch=None):
    """
    Add a new file to the repository.
    """
    file_path = file_name.strip('/')

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {
        "message": message,
        # The GitHub contents API requires base64-encoded content
        "content": base64.b64encode(content.encode('utf-8')).decode('utf-8'),
    }
    if branch:
        data["branch"] = branch

    try:
        response = requests.put(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to create file: {_error_details(e)}")
        return None

def update_file(owner, repo, path, content, sha, message, branch=None):
    """
    Modify the content of an existing file.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}

    encoded_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')

    data = {
        "message": message,
        "content": encoded_content,
        "sha": sha
    }
    if branch:
        data["branch"] = branch

    try:
        response = requests.put(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to update file: {_error_details(e)}")
        return None

def fetch_file_sha(owner, repo, path, branch=None):
    """
    Fetch the SHA for the given file path in the repository.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}
    params = {"ref": branch} if branch else {}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('sha')
    except requests.RequestException as e:
        logging.error(f"Failed to fetch file SHA: {e}")
        return None

def delete_file(owner, repo, path, sha, message, branch=None):
    """
    Remove a file from the repository. Looks up the file's SHA if not given.
    """
    if not sha:
        sha = fetch_file_sha(owner, repo, path, branch)
        if not sha:
            logging.error("Unable to fetch SHA for the file. Aborting deletion.")
            return None

    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    access_token = get_installation_access_token()
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {"message": message, "sha": sha}
    if branch:
        data["branch"] = branch

    try:
        response = requests.delete(url, headers=headers, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logging.error(f"Failed to delete file: {_error_details(e)}")
        return None

def _github_error_message(e):
    """A short, user-facing reason for a failed GitHub request."""
    response = getattr(e, 'response', None)
    if response is None:
        return "Could not reach GitHub"
    try:
        message = response.json().get('message')
    except ValueError:
        message = None
    return message or f"GitHub returned status {response.status_code}"

def github_api(method, path, access_token, **kwargs):
    """
    Call the GitHub REST API. Returns (json_or_None, None) on success or (None, error_message).
    `path` is relative to https://api.github.com and must already be URL-safe.
    """
    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'}
    try:
        response = requests.request(method, f'https://api.github.com{path}', headers=headers,
                                    timeout=REQUEST_TIMEOUT, **kwargs)
        response.raise_for_status()
        # Some endpoints answer 201/202/204 with an empty body
        return (response.json() if response.status_code != 204 and response.content else None), None
    except RequestException as e:
        logging.error(f"GitHub API {method} {path} failed: {_error_details(e)}")
        return None, _github_error_message(e)

def search_issues(query, access_token, sort='updated', order='desc', page=1, per_page=50):
    """
    Search issues and pull requests (GET /search/issues).
    Returns ({'total_count', 'items', ...}, None) or (None, error_message).
    """
    params = {'q': query, 'sort': sort, 'order': order, 'page': page, 'per_page': per_page}
    return github_api('GET', '/search/issues', access_token, params=params)

def _ref(name):
    """URL-encode a branch name for use in an API path (slashes are kept)."""
    return quote(name, safe='/')

def get_repository(owner, repo, access_token):
    """Returns (repository, None) or (None, error_message)."""
    return github_api('GET', f'/repos/{owner}/{repo}', access_token)

def delete_repository_by_name(owner, repo, access_token):
    """Permanently delete a repository. Returns (True, None) or (False, error_message)."""
    _, error = github_api('DELETE', f'/repos/{owner}/{repo}', access_token)
    return error is None, error

def list_branches(owner, repo, access_token):
    """
    Up to 100 branches as returned by GitHub (each has 'name' and 'protected').
    Returns (branches, None) or (None, error_message).
    """
    return github_api('GET', f'/repos/{owner}/{repo}/branches', access_token, params={'per_page': 100})

def compare_refs(owner, repo, base, head, access_token):
    """
    Compare two refs. `head` may be 'other_owner:branch' when comparing across forks.
    Returns (comparison, None) or (None, error_message).
    """
    return github_api('GET', f'/repos/{owner}/{repo}/compare/{_ref(base)}...{_ref(head)}', access_token)

def delete_branch_ref(owner, repo, branch, access_token):
    """Delete a branch. Returns (True, None) or (False, error_message)."""
    _, error = github_api('DELETE', f'/repos/{owner}/{repo}/git/refs/heads/{_ref(branch)}', access_token)
    return error is None, error

def update_repository(owner, repo, access_token, fields):
    """
    Update repository settings, e.g. {'archived': True}, {'private': False}
    or {'default_branch': 'main'}.
    Returns (repository, None) on success or (None, error_message).
    """
    url = f'https://api.github.com/repos/{owner}/{repo}'
    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'}

    try:
        response = requests.patch(url, headers=headers, json=fields, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json(), None
    except RequestException as e:
        logging.error(f"Failed to update repository '{owner}/{repo}' with {fields}: {_error_details(e)}")
        return None, _github_error_message(e)

def get_repository_topics(owner, repo, access_token):
    """
    Returns (list_of_topics, None) on success or (None, error_message).
    """
    url = f'https://api.github.com/repos/{owner}/{repo}/topics'
    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'}

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('names', []), None
    except RequestException as e:
        logging.error(f"Failed to fetch topics for '{owner}/{repo}': {_error_details(e)}")
        return None, _github_error_message(e)

def replace_repository_topics(owner, repo, access_token, topics):
    """
    Replace all of a repository's topics with `topics`.
    Returns (list_of_topics, None) on success or (None, error_message).
    """
    url = f'https://api.github.com/repos/{owner}/{repo}/topics'
    headers = {'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'}

    try:
        response = requests.put(url, headers=headers, json={'names': topics}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.json().get('names', []), None
    except RequestException as e:
        logging.error(f"Failed to set topics for '{owner}/{repo}': {_error_details(e)}")
        return None, _github_error_message(e)
