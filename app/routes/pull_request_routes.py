"""pull_request_routes.py

Listing, creating, reviewing and merging pull requests (issue #40).
"""
import logging
from flask import flash, render_template, request, redirect, url_for, session
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago
from app.controllers.repo_controller import get_branches
from app.controllers.pull_requests_controller import (
    MAX_FILES, STATES,
    allowed_merge_methods, apply_pull_request_action, can_delete_head_branch, create_pull_request,
    diff_lines, get_pull_request, get_review_data, list_pull_requests, merge_status, parse_state,
    summarize_checks, summarize_reviews,
)

def _parse_pr_number(value):
    """Return the PR number as an int, or None if it is not a valid number."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _ago(value):
    return time_ago(parse_github_date(value))


@main_routes.route('/repositories/<repo_name>/pull_requests', methods=['GET', 'POST'])
@login_required
def manage_pull_requests(repo_name):
    """
    GET: lists pull requests (open / closed / all), shows one with `?pr_number=N`,
    or renders the create form with `?create=1`.
    POST: creates a pull request.
    """
    access_token = get_installation_access_token()
    if not access_token:
        logging.error("Failed to get access token for managing pull requests.")
        return "Failed to authenticate with GitHub", 500

    owner = session.get('github_username')

    if request.method == 'GET':
        pr_number_arg = request.args.get('pr_number')
        if pr_number_arg:
            pr_number = _parse_pr_number(pr_number_arg)
            if pr_number is None:
                return "Pull request number must be a number", 400
            return _render_pull_request(owner, repo_name, pr_number, access_token)

        if request.args.get('create'):
            branches = get_branches(owner, repo_name=repo_name)
            if branches is None:
                logging.error(f"Failed to fetch branches for repository {repo_name}.")
                return "Failed to fetch branches from GitHub", 500
            return render_template('create_pull_request.html', repo_name=repo_name, branches=branches)

        state = parse_state(request.args.get('state'))
        pull_requests, error = list_pull_requests(owner, repo_name, access_token, state)
        if error:
            logging.error(f"Failed to fetch pull requests for repository {repo_name}: {error}")
            return f"Failed to fetch pull requests from GitHub: {error}", 500
        for pull in pull_requests:
            pull['updated_ago'] = _ago(pull.get('updated_at'))
        return render_template('pull_requests.html', repo_name=repo_name, pull_requests=pull_requests,
                               state=state, states=STATES)

    if request.form.get('action') != 'create':
        return "Unknown action", 400

    title = (request.form.get('title') or '').strip()
    body = request.form.get('body')
    head = request.form.get('head')
    base = request.form.get('base')
    if not title or not head or not base:
        return "Title, head branch, and base branch are required to create a pull request", 400
    new_pr = create_pull_request(owner, repo_name=repo_name, title=title, body=body, head=head, base=base)
    if new_pr:
        logging.info(f"Pull request created successfully in repository {repo_name}.")
        if new_pr.get('number'):
            return redirect(url_for('main.manage_pull_requests', repo_name=repo_name, pr_number=new_pr['number']))
        return redirect(url_for('main.manage_pull_requests', repo_name=repo_name))
    return "Failed to create pull request", 500


def _render_pull_request(owner, repo_name, pr_number, access_token):
    """The pull request page: description, merge box, checks, reviews and changed files."""
    pull, error = get_pull_request(owner, repo_name, pr_number, access_token)
    if error:
        logging.error(f"Failed to fetch pull request #{pr_number} in {repo_name}: {error}")
        status = 404 if error == 'Not Found' else 500
        return f"Failed to fetch details for pull request #{pr_number}: {error}", status

    review = get_review_data(owner, repo_name, pull, access_token)
    for key, error in review['errors'].items():
        flash(f"Couldn't load {key.replace('_', ' ')}: {error}", 'error')
    for item in review['reviews'] + review['review_comments']:
        item['ago'] = _ago(item.get('submitted_at') or item.get('created_at'))
    for changed_file in review['files']:
        changed_file['lines'] = diff_lines(changed_file.get('patch'))
    pull['created_ago'] = _ago(pull.get('created_at'))

    merge_level, merge_message = merge_status(pull)
    return render_template(
        'pull_request_details.html', repo_name=repo_name, pull_request=pull,
        files=review['files'], files_truncated=(pull.get('changed_files') or 0) > len(review['files']),
        max_files=MAX_FILES,
        reviews=[r for r in review['reviews'] if r.get('body') or r.get('state') != 'COMMENTED'],
        review_summary=summarize_reviews(review['reviews']), review_comments=review['review_comments'],
        check_runs=review['check_runs'], checks=summarize_checks(review['check_runs']),
        merge_level=merge_level, merge_message=merge_message,
        merge_methods=allowed_merge_methods(pull), can_delete_branch=can_delete_head_branch(pull),
    )


@main_routes.route('/repositories/<repo_name>/pull_requests/<int:pr_number>', methods=['POST'])
@login_required
def pull_request_action(repo_name, pr_number):
    """Merge (with a chosen method), close or reopen a pull request."""
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500
    owner = session.get('github_username')
    action = request.form.get('action')

    messages, error = apply_pull_request_action(owner, repo_name, pr_number, access_token, action, request.form)
    if error:
        logging.warning(f"Pull request action '{action}' on {repo_name}#{pr_number} failed: {error}")
        flash(error, 'error')
    else:
        for category, message in messages:
            flash(message, category)
    return redirect(url_for('main.manage_pull_requests', repo_name=repo_name, pr_number=pr_number))
