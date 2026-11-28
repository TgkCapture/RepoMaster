"""actions_controller.py

GitHub Actions panel (issue #45): workflows, runs, jobs, re-run / cancel, manual dispatch
with inputs, log downloads and repository secrets.
Most calls go through repo_controller.github_api, which returns (json_or_None, error_message).
"""
import base64
import binascii
import logging
import re
from urllib.parse import quote
from app import github_http
import yaml
from nacl import encoding, public
from requests.exceptions import RequestException
from app.controllers.branch_management_controller import valid_branch
from app.controllers.repo_controller import REQUEST_TIMEOUT, _error_details, _github_error_message, github_api

RUNS_PER_PAGE = 30
RUN_STATUSES = {'': 'Any status', 'in_progress': 'In progress', 'queued': 'Queued', 'success': 'Succeeded',
                'failure': 'Failed', 'cancelled': 'Cancelled'}
RUN_ACTIONS = {'rerun_failed': ('rerun-failed-jobs', "Re-running failed jobs."),
               'rerun': ('rerun', "Re-running all jobs."),
               'cancel': ('cancel', "Cancelling the run.")}
SECRET_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,99}$')
MAX_SECRET_BYTES = 48 * 1024
MAX_INPUT_LENGTH = 65536
MAX_WORKFLOW_FILE_BYTES = 512 * 1024


def _repo_path(owner, repo):
    return f'/repos/{quote(owner, safe="")}/{quote(repo, safe="")}'


# --- Display helpers ---------------------------------------------------------

def run_state(item):
    """
    One label and Bootstrap colour for a run, job or step: the conclusion when it's finished,
    otherwise its status. Every state has a text label, so colour is never the only cue.
    """
    if item.get('status') != 'completed':
        state = item.get('status') or 'unknown'
        return state.replace('_', ' '), 'warning' if state == 'in_progress' else 'secondary'
    conclusion = item.get('conclusion') or 'unknown'
    colour = {'success': 'success', 'failure': 'danger', 'timed_out': 'danger', 'startup_failure': 'danger',
              'cancelled': 'secondary', 'skipped': 'secondary', 'neutral': 'secondary',
              'action_required': 'warning'}.get(conclusion, 'secondary')
    return conclusion.replace('_', ' '), colour


def parse_page(value):
    try:
        return max(1, min(int(value), 34))  # GitHub returns at most 1,000 runs
    except (TypeError, ValueError):
        return 1


# --- Workflows and runs ------------------------------------------------------

def list_workflows(owner, repo, access_token):
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/actions/workflows', access_token,
                             params={'per_page': 100})
    return (None, error) if error else ((data or {}).get('workflows', []), None)


def list_runs(owner, repo, access_token, workflow_id=None, status='', page=1):
    """Recent runs, newest first, optionally for one workflow and status. Returns ({runs, total}, error)."""
    path = (f'{_repo_path(owner, repo)}/actions/workflows/{int(workflow_id)}/runs' if workflow_id
            else f'{_repo_path(owner, repo)}/actions/runs')
    params = {'per_page': RUNS_PER_PAGE, 'page': page}
    if status in RUN_STATUSES and status:
        params['status'] = status
    data, error = github_api('GET', path, access_token, params=params)
    if error:
        return None, error
    return {'runs': data.get('workflow_runs', []), 'total': data.get('total_count', 0)}, None


def get_run(owner, repo, run_id, access_token):
    return github_api('GET', f'{_repo_path(owner, repo)}/actions/runs/{int(run_id)}', access_token)


def list_jobs(owner, repo, run_id, access_token):
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/actions/runs/{int(run_id)}/jobs', access_token,
                             params={'per_page': 100})
    return (None, error) if error else ((data or {}).get('jobs', []), None)


def run_action(owner, repo, run, action, access_token):
    """Re-run failed jobs, re-run everything, or cancel. Returns (message, error)."""
    if action not in RUN_ACTIONS:
        return None, "Unknown action."
    finished = run.get('status') == 'completed'
    if action == 'cancel' and finished:
        return None, "This run has already finished."
    if action != 'cancel' and not finished:
        return None, "Wait for the run to finish before re-running it."
    if action == 'rerun_failed' and run.get('conclusion') not in ('failure', 'cancelled', 'timed_out', 'startup_failure'):
        return None, "This run has no failed jobs to re-run."
    endpoint, message = RUN_ACTIONS[action]
    _, error = github_api('POST', f'{_repo_path(owner, repo)}/actions/runs/{int(run["id"])}/{endpoint}', access_token)
    return (None, error) if error else (message, None)


def get_logs_url(owner, repo, run_id, access_token):
    """
    GitHub answers the logs endpoint with a redirect to a short-lived download URL.
    Returns (url, error) without downloading the archive.
    """
    url = f'https://api.github.com{_repo_path(owner, repo)}/actions/runs/{int(run_id)}/logs'
    try:
        response = github_http.get(url, allow_redirects=False, timeout=REQUEST_TIMEOUT,
                                headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/vnd.github+json'})
        if response.status_code == 302 and response.headers.get('Location', '').startswith('https://'):
            return response.headers['Location'], None
        response.raise_for_status()
        return None, "GitHub didn't return a download link."
    except RequestException as e:
        logging.error(f"Fetching logs for run {run_id} in {owner}/{repo} failed: {_error_details(e)}")
        return None, _github_error_message(e)


# --- Manual dispatch ---------------------------------------------------------

def get_dispatch_inputs(owner, repo, workflow, ref, access_token):
    """
    Read the workflow file and return (inputs, error), where inputs is None if the workflow
    can't be run manually (no `workflow_dispatch` trigger), else an ordered list of
    {name, description, required, default, type, options}.
    """
    path = workflow.get('path') or ''
    if not path.startswith('.github/workflows/'):
        return None, "This workflow isn't defined by a file in .github/workflows."
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/contents/{quote(path, safe="/")}', access_token,
                             params={'ref': ref})
    if error:
        return None, error
    if (data.get('size') or 0) > MAX_WORKFLOW_FILE_BYTES or data.get('encoding') != 'base64':
        return None, "The workflow file is too large to read."
    try:
        document = yaml.safe_load(base64.b64decode(data.get('content') or ''))
    except (binascii.Error, ValueError, yaml.YAMLError):
        return None, "The workflow file couldn't be read as YAML."
    return parse_dispatch_inputs(document), None


def parse_dispatch_inputs(document):
    """The workflow_dispatch inputs of a parsed workflow, or None if it has no workflow_dispatch."""
    if not isinstance(document, dict):
        return None
    # YAML 1.1 reads a bare `on:` key as the boolean True
    triggers = document.get('on', document.get(True))
    if triggers == 'workflow_dispatch' or (isinstance(triggers, list) and 'workflow_dispatch' in triggers):
        return []
    if not isinstance(triggers, dict) or 'workflow_dispatch' not in triggers:
        return None
    inputs = (triggers.get('workflow_dispatch') or {}).get('inputs') or {}
    if not isinstance(inputs, dict):
        return []
    result = []
    for name, spec in inputs.items():
        spec = spec if isinstance(spec, dict) else {}
        input_type = spec.get('type') or 'string'
        default = spec.get('default')
        if isinstance(default, bool):
            default = 'true' if default else 'false'
        result.append({
            'name': str(name),
            'description': str(spec.get('description') or ''),
            'required': bool(spec.get('required')),
            'default': '' if default is None else str(default),
            'type': input_type if input_type in ('string', 'choice', 'boolean', 'number', 'environment') else 'string',
            'options': [str(option) for option in spec.get('options') or []],
        })
    return result


def validate_dispatch(form, inputs, branch_names):
    """Check the dispatch form against the workflow's inputs. Returns ({ref, inputs}, error)."""
    ref = (form.get('ref') or '').strip()
    if ref not in branch_names or not valid_branch(ref):
        return None, "Choose the branch to run the workflow on."
    values = {}
    for spec in inputs:
        name = spec['name']
        if spec['type'] == 'boolean':
            value = 'true' if form.get(f'input_{name}') == 'on' else 'false'
        else:
            value = (form.get(f'input_{name}') or '').strip()
        if len(value) > MAX_INPUT_LENGTH:
            return None, f"'{name}' is too long."
        if spec['required'] and value == '':
            return None, f"'{name}' is required."
        if spec['type'] == 'choice' and value and value not in spec['options']:
            return None, f"Choose one of the options for '{name}'."
        if spec['type'] == 'number' and value:
            try:
                float(value)
            except ValueError:
                return None, f"'{name}' must be a number."
        if value != '':
            values[name] = value
    return {'ref': ref, 'inputs': values}, None


def dispatch_workflow(owner, repo, workflow_id, request_body, access_token):
    _, error = github_api('POST', f'{_repo_path(owner, repo)}/actions/workflows/{int(workflow_id)}/dispatches',
                          access_token, json=request_body)
    return error


# --- Secrets -----------------------------------------------------------------

def list_secrets(owner, repo, access_token):
    """Secret names and when they were last updated (GitHub never returns values)."""
    data, error = github_api('GET', f'{_repo_path(owner, repo)}/actions/secrets', access_token,
                             params={'per_page': 100})
    return (None, error) if error else ((data or {}).get('secrets', []), None)


def validate_secret(name, value):
    name = (name or '').strip().upper()
    if not SECRET_NAME_PATTERN.match(name):
        return None, "Secret names can only contain letters, numbers and underscores, and can't start with a number."
    if name.startswith('GITHUB_'):
        return None, "Secret names can't start with GITHUB_."
    if not value:
        return None, "Enter a value for the secret."
    if len(value.encode('utf-8')) > MAX_SECRET_BYTES:
        return None, "Secrets can be at most 48 KB."
    return name, None


def encrypt_secret(public_key_b64, value):
    """Encrypt a secret value with the repository's public key (libsodium sealed box), base64-encoded."""
    key = public.PublicKey(public_key_b64.encode('utf-8'), encoding.Base64Encoder())
    return base64.b64encode(public.SealedBox(key).encrypt(value.encode('utf-8'))).decode('ascii')


def set_secret(owner, repo, name, value, access_token):
    """Create or update a secret. The value is encrypted before it leaves RepoMaster. Returns error or None."""
    key, error = github_api('GET', f'{_repo_path(owner, repo)}/actions/secrets/public-key', access_token)
    if error:
        return error
    try:
        encrypted = encrypt_secret(key['key'], value)
    except (KeyError, TypeError, ValueError) as e:
        logging.error(f"Encrypting a secret for {owner}/{repo} failed: {type(e).__name__}")
        return "GitHub returned an unusable encryption key."
    _, error = github_api('PUT', f'{_repo_path(owner, repo)}/actions/secrets/{quote(name, safe="")}', access_token,
                          json={'encrypted_value': encrypted, 'key_id': key.get('key_id')})
    return error


def delete_secret(owner, repo, name, access_token):
    if not SECRET_NAME_PATTERN.match(name or ''):
        return "Invalid secret name."
    _, error = github_api('DELETE', f'{_repo_path(owner, repo)}/actions/secrets/{quote(name, safe="")}', access_token)
    return error
