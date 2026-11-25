"""issue_routes.py

Listing, creating, viewing and managing issues (issue #39).
"""
import logging
from flask import flash, render_template, request, redirect, session, url_for
from app.routes import main_routes
from app.controllers.auth_controller import get_installation_access_token, login_required
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import COLOR_PATTERN, label_text_color, time_ago
from app.controllers.issues_controller import (
    CLOSE_REASONS, STATES,
    apply_issue_action, create_github_issue, get_issue, get_issue_options,
    list_issue_comments, list_issues, parse_issue_number, parse_state,
)


def _label_style(label):
    """Inline badge colors for a GitHub label (colors are validated before use)."""
    color = label.get('color') or ''
    color = color if COLOR_PATTERN.match(color) else 'cccccc'
    return f"background-color: #{color}; color: {label_text_color(color)};"


def _ago(value):
    return time_ago(parse_github_date(value))


@main_routes.route('/repositories/<repo_name>/issues', methods=['GET', 'POST'])
@login_required
def manage_issues(repo_name):
    """
    GET: lists the repository's issues, filtered by state (open / closed / all).
    POST: creates an issue, or closes / reopens one from the list.
    """
    # Older links pass ?issue_number=N; send them to the issue's own page.
    legacy_number = parse_issue_number(request.args.get('issue_number'))
    if request.method == 'GET' and legacy_number:
        return redirect(url_for('main.issue_detail', repo_name=repo_name, issue_number=legacy_number))

    owner = session.get('github_username')
    state = parse_state(request.values.get('state'))
    action = request.form.get('action')

    access_token = None
    if request.method == 'GET' or action in ('close', 'reopen'):
        access_token = get_installation_access_token()
        if not access_token:
            return "Failed to authenticate with GitHub", 500

    if request.method == 'GET':
        issues, error = list_issues(owner, repo_name, access_token, state)
        if error:
            logging.error(f"Failed to fetch issues for repository {repo_name}: {error}")
            return f"Failed to fetch issues from GitHub: {error}", 500
        for issue in issues:
            issue['created_ago'] = _ago(issue.get('created_at'))
        return render_template('issues.html', repo_name=repo_name, issues=issues, state=state,
                               states=STATES, label_style=_label_style)

    if action in ('close', 'reopen'):
        issue_number = parse_issue_number(request.form.get('issue_number'))
        if not issue_number:
            return "Issue number is required", 400
        message, error = apply_issue_action(owner, repo_name, issue_number, access_token, action, request.form)
        if error:
            flash(f"Issue #{issue_number}: {error}", 'error')
        else:
            flash(f"Issue #{issue_number}: {message}", 'success')
        return redirect(url_for('main.manage_issues', repo_name=repo_name, state=state))

    # Create a new issue
    title = (request.form.get('title') or '').strip()
    body = request.form.get('body')
    if not title:
        return "Issue title is required", 400
    new_issue = create_github_issue(repo_name, title, body)
    if new_issue:
        logging.info(f"Issue created successfully in repository {repo_name}.")
        flash(f"Issue #{new_issue.get('number')} created.", 'success')
        if new_issue.get('number'):
            return redirect(url_for('main.issue_detail', repo_name=repo_name, issue_number=new_issue['number']))
        return redirect(url_for('main.manage_issues', repo_name=repo_name))
    return "Failed to create the issue", 500


@main_routes.route('/repositories/<repo_name>/issues/<int:issue_number>', methods=['GET'])
@login_required
def issue_detail(repo_name, issue_number):
    """One issue with its comments, labels, assignees and milestone."""
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500
    owner = session.get('github_username')

    issue, error = get_issue(owner, repo_name, issue_number, access_token)
    if error:
        logging.error(f"Failed to fetch issue #{issue_number} in {repo_name}: {error}")
        status = 404 if error == 'Not Found' else 500
        return f"Failed to fetch issue #{issue_number}: {error}", status
    if 'pull_request' in issue:
        # Pull requests share issue numbers; show them on the pull request page.
        return redirect(url_for('main.manage_pull_requests', repo_name=repo_name, pr_number=issue_number))

    comments, error = list_issue_comments(owner, repo_name, issue_number, access_token)
    if error:
        flash(f"Couldn't load comments: {error}", 'error')
        comments = []
    issue['created_ago'] = _ago(issue.get('created_at'))
    for comment in comments:
        comment['created_ago'] = _ago(comment.get('created_at'))

    options = get_issue_options(owner, repo_name, access_token)
    current_labels = {label.get('name') for label in issue.get('labels') or []}
    current_assignees = {user.get('login') for user in issue.get('assignees') or []}

    return render_template(
        'issue_detail.html', repo_name=repo_name, issue=issue, comments=comments,
        available_labels=[l for l in options['labels'] if l.get('name') not in current_labels],
        available_assignees=[u for u in options['assignees'] if u.get('login') not in current_assignees],
        milestones=options['milestones'], close_reasons=CLOSE_REASONS, label_style=_label_style,
    )


@main_routes.route('/repositories/<repo_name>/issues/<int:issue_number>', methods=['POST'])
@login_required
def issue_action(repo_name, issue_number):
    """Edit, close/reopen, comment on, label, assign or set the milestone of an issue."""
    access_token = get_installation_access_token()
    if not access_token:
        return "Failed to authenticate with GitHub", 500
    owner = session.get('github_username')
    action = request.form.get('action')

    # Only offer milestones that exist; fetched just for this action.
    options = get_issue_options(owner, repo_name, access_token) if action == 'set_milestone' else None
    message, error = apply_issue_action(owner, repo_name, issue_number, access_token, action, request.form, options)
    if error:
        logging.warning(f"Issue action '{action}' on {repo_name}#{issue_number} failed: {error}")
        flash(error, 'error')
    else:
        flash(message, 'success')
    return redirect(url_for('main.issue_detail', repo_name=repo_name, issue_number=issue_number))
