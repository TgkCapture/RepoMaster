"""notification_routes.py

GitHub webhook receiver and in-app notifications (issue #46).
"""
import json
import logging
from flask import current_app, flash, jsonify, redirect, render_template, request, session, url_for
from app.routes import main_routes
from app.controllers.auth_controller import is_user_logged_in, login_required
from app.controllers.cleanup_controller import parse_github_date
from app.controllers.inbox_controller import time_ago
from app.controllers.notifications_controller import (
    get_notification, handle_delivery, list_notifications, mark_read, safe_link, unread_count, verify_signature,
)


@main_routes.route('/github/webhook', methods=['POST'])
def github_webhook():
    """
    Receives the GitHub App's webhook deliveries. Not behind login: GitHub authenticates
    each delivery with an HMAC signature of the body, made with the shared webhook secret.
    """
    secret = current_app.config.get('GITHUB_WEBHOOK_SECRET')
    if not secret:
        logging.error("Webhook received but GITHUB_WEBHOOK_SECRET is not set; refusing it.")
        return jsonify(error='webhook secret not configured'), 503

    body = request.get_data(cache=False)
    if not verify_signature(secret, body, request.headers.get('X-Hub-Signature-256')):
        logging.warning("Webhook with a missing or invalid signature rejected.")
        return jsonify(error='invalid signature'), 401
    try:
        payload = json.loads(body)
    except ValueError:
        return jsonify(error='invalid JSON'), 400
    if not isinstance(payload, dict):
        return jsonify(error='invalid payload'), 400

    event = request.headers.get('X-GitHub-Event', '')
    delivery_id = request.headers.get('X-GitHub-Delivery') or None
    result = handle_delivery(event, delivery_id, payload)
    logging.info(f"Webhook {event} ({delivery_id}): {result}")
    return jsonify(result=result), 200


@main_routes.app_context_processor
def notification_bell():
    """Unread count for the bell on pages that show it (0 when signed out)."""
    def count():
        if not is_user_logged_in():
            return 0
        try:
            return unread_count(session['installation_id'])
        except Exception:  # never break a page because the bell couldn't be counted
            logging.exception("Couldn't count unread notifications")
            return 0
    return {'unread_notifications': count}


@main_routes.route('/notifications', methods=['GET'])
@login_required
def notifications():
    items = list_notifications(session['installation_id'])
    for item in items:
        item['ago'] = time_ago(parse_github_date(item['created_at']))
    return render_template('notifications.html', notifications=items)


@main_routes.route('/notifications/read-all', methods=['POST'])
@login_required
def notifications_read_all():
    mark_read(session['installation_id'])
    flash("All notifications marked as read.", 'success')
    return redirect(url_for('main.notifications'))


@main_routes.route('/notifications/<int:notification_id>/open', methods=['GET'])
@login_required
def open_notification(notification_id):
    """Mark a notification as read and go to what it's about."""
    notification = get_notification(session['installation_id'], notification_id)
    if notification is None:
        return "Notification not found", 404
    mark_read(session['installation_id'], notification_id)
    return redirect(safe_link(notification['link']) or url_for('main.notifications'))


@main_routes.route('/notifications/unread.json', methods=['GET'])
@login_required
def notifications_unread():
    """Polled by the bell so it updates without reloading the page."""
    return jsonify(unread=unread_count(session['installation_id']))
