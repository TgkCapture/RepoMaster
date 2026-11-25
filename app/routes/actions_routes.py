"""actions_routes.py

GitHub Actions panel (issue #45).
"""
import logging
from flask import flash, redirect, render_template, request, url_for
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.branch_management_controller import valid_names
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago
from app.controllers.repo_controller import get_repository, list_branches
from app.controllers.actions_controller import (
    RUN_STATUSES, RUNS_PER_PAGE,
    delete_secret, dispatch_workflow, get_dispatch_inputs, get_logs_url, get_run, list_jobs, list_runs,
    list_secrets, list_workflows, parse_page, run_action, run_state, set_secret, validate_dispatch,
    validate_secret,
)


def _start(owner, repo):
    """(access_token, None) or (None, error_response)."""
    if not valid_names(owner, repo):
        return None, ("Invalid repository name", 400)
    access_token = get_installation_access_token()
    if not access_token:
        return None, ("Failed to authenticate with GitHub", 500)
    return access_token, None


def _ago(value):
    return time_ago(parse_github_date(value))


def _duration(start, end):
    """'3m 12s' between two GitHub timestamps, or '' if unknown."""
    start, end = parse_github_date(start), parse_github_date(end)
    if not start or not end:
        return ''
    seconds = max(0, int((end - start).total_seconds()))
    return f"{seconds // 60}m {seconds % 60}s" if seconds >= 60 else f"{seconds}s"


@main_routes.route('/repos/<owner>/<repo>/actions', methods=['GET'])
@login_required
def actions_overview(owner, repo):
    """Workflows and recent runs, filterable by workflow and status."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    workflows, error = list_workflows(owner, repo, access_token)
    if error:
        return f"Failed to fetch workflows: {error}", 500

    workflow_ids = {w['id'] for w in workflows}
    try:
        workflow_id = int(request.args.get('workflow') or 0) or None
    except ValueError:
        workflow_id = None
    if workflow_id not in workflow_ids:
        workflow_id = None
    status = request.args.get('status', '')
    status = status if status in RUN_STATUSES else ''
    page = parse_page(request.args.get('page'))

    result, error = list_runs(owner, repo, access_token, workflow_id, status, page)
    runs = (result or {}).get('runs', [])
    if error:
        flash(f"Couldn't load runs: {error}", 'error')
    for run in runs:
        run['state'] = run_state(run)
        run['ago'] = _ago(run.get('run_started_at') or run.get('created_at'))
    total = (result or {}).get('total', 0)
    return render_template('actions.html', owner=owner, repo=repo, workflows=workflows, runs=runs,
                           workflow_id=workflow_id, status=status, statuses=RUN_STATUSES, page=page,
                           has_next=page * RUNS_PER_PAGE < min(total, 1000))


@main_routes.route('/repos/<owner>/<repo>/actions/runs/<int:run_id>', methods=['GET'])
@login_required
def actions_run(owner, repo, run_id):
    """One run with its jobs and steps."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    run, error = get_run(owner, repo, run_id, access_token)
    if error:
        return f"Failed to fetch the run: {error}", 404 if error == 'Not Found' else 500
    jobs, error = list_jobs(owner, repo, run_id, access_token)
    if error:
        flash(f"Couldn't load jobs: {error}", 'error')
        jobs = []
    run['state'] = run_state(run)
    run['ago'] = _ago(run.get('run_started_at') or run.get('created_at'))
    for job in jobs:
        job['state'] = run_state(job)
        job['duration'] = _duration(job.get('started_at'), job.get('completed_at'))
        for step in job.get('steps') or []:
            step['state'] = run_state(step)
    return render_template('actions_run.html', owner=owner, repo=repo, run=run, jobs=jobs)


@main_routes.route('/repos/<owner>/<repo>/actions/runs/<int:run_id>', methods=['POST'])
@login_required
def actions_run_action(owner, repo, run_id):
    """Re-run failed jobs, re-run all jobs, or cancel a run."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    run, error = get_run(owner, repo, run_id, access_token)
    if not error:
        message, error = run_action(owner, repo, run, request.form.get('action'), access_token)
    if error:
        flash(error, 'error')
    else:
        flash(message, 'success')
    return redirect(url_for('main.actions_run', owner=owner, repo=repo, run_id=run_id))


@main_routes.route('/repos/<owner>/<repo>/actions/runs/<int:run_id>/logs', methods=['GET'])
@login_required
def actions_run_logs(owner, repo, run_id):
    """Send the browser to GitHub's short-lived download link for the run's logs (a .zip)."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    url, error = get_logs_url(owner, repo, run_id, access_token)
    if error:
        flash(f"Couldn't get the logs: {error}", 'error')
        return redirect(url_for('main.actions_run', owner=owner, repo=repo, run_id=run_id))
    return redirect(url)


@main_routes.route('/repos/<owner>/<repo>/actions/workflows/<int:workflow_id>/dispatch', methods=['GET', 'POST'])
@login_required
def actions_dispatch(owner, repo, workflow_id):
    """Run a workflow manually (workflow_dispatch), with its inputs."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure
    workflows, error = list_workflows(owner, repo, access_token)
    if error:
        return f"Failed to fetch workflows: {error}", 500
    workflow = next((w for w in workflows if w['id'] == workflow_id), None)
    if workflow is None:
        return "Workflow not found", 404

    branches, error = list_branches(owner, repo, access_token)
    if error:
        return f"Failed to fetch branches: {error}", 500
    branch_names = [b['name'] for b in branches]
    repository, _ = get_repository(owner, repo, access_token)
    default_branch = (repository or {}).get('default_branch')
    ref = request.values.get('ref') or default_branch
    if ref not in branch_names:
        ref = default_branch

    inputs, error = get_dispatch_inputs(owner, repo, workflow, ref, access_token)
    context = {'owner': owner, 'repo': repo, 'workflow': workflow, 'branches': branch_names, 'ref': ref,
               'inputs': inputs, 'load_error': error, 'form': {}}
    if request.method == 'GET' or error or inputs is None:
        if request.method == 'POST':
            flash(error or "This workflow can't be run manually.", 'error')
        return render_template('actions_dispatch.html', **context)

    request_body, error = validate_dispatch(request.form, inputs, branch_names)
    if not error:
        error = dispatch_workflow(owner, repo, workflow_id, request_body, access_token)
    if error:
        logging.warning(f"Dispatching workflow {workflow_id} in {owner}/{repo} failed: {error}")
        flash(f"Couldn't start the workflow: {error}", 'error')
        return render_template('actions_dispatch.html', **{**context, 'form': request.form}), 400
    flash(f"Started {workflow.get('name')} on {request_body['ref']}. It can take a few seconds to appear.", 'success')
    return redirect(url_for('main.actions_overview', owner=owner, repo=repo, workflow=workflow_id))


@main_routes.route('/repos/<owner>/<repo>/actions/secrets', methods=['GET', 'POST'])
@login_required
def actions_secrets(owner, repo):
    """Repository secrets: names only. Values are encrypted in RepoMaster and can't be read back."""
    access_token, failure = _start(owner, repo)
    if failure:
        return failure

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            name = request.form.get('name', '')
            error = delete_secret(owner, repo, name, access_token)
            flash(f"Couldn't delete {name}: {error}" if error else f"Secret {name} deleted.",
                  'error' if error else 'success')
        else:
            name, error = validate_secret(request.form.get('name'), request.form.get('value'))
            if not error:
                error = set_secret(owner, repo, name, request.form.get('value'), access_token)
            # The value is never echoed back or logged, even when saving fails.
            flash(f"Couldn't save the secret: {error}" if error else f"Secret {name} saved.",
                  'error' if error else 'success')
        return redirect(url_for('main.actions_secrets', owner=owner, repo=repo))

    secrets, error = list_secrets(owner, repo, access_token)
    if error:
        flash(f"Couldn't load secrets: {error}", 'error')
        secrets = []
    for secret in secrets:
        secret['ago'] = _ago(secret.get('updated_at'))
    return render_template('actions_secrets.html', owner=owner, repo=repo, secrets=secrets)
