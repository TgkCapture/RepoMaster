"""Smoke tests for the application factory, configuration and route registration."""
import pytest
from app import create_app
from app.config.production_config import ProductionConfig
from app.controllers.auth_controller import load_private_key

# Every endpoint the app exposed before routes were split into modules.
EXPECTED_ENDPOINTS = {
    'main.home',
    'main.logout',
    'main.github_authorize',
    'main.install_github_app',
    'main.login',
    'main.github_callback',
    'main.bulk_actions',
    'main.bulk_actions_confirm',
    'main.bulk_actions_apply',
    'main.cleanup_dashboard',
    'main.cleanup_branches',
    'main.cleanup_delete_branches',
    'main.inbox',
    'main.new_repository',
    'main.new_repository_result',
    'main.show_github_repositories',
    'main.show_repo_details',
    'main.delete_repositories',
    'main.manage_issues',
    'main.issue_detail',
    'main.issue_action',
    'main.manage_pull_requests',
    'main.pull_request_action',
    'main.main_create_branch',
    'main.show_branch_details',
    'main.delete_branch',
    'main.rename_branch',
    'main.branch_protection',
    'main.compare_branches_page',
    'main.get_contents',
    'main.create_new_file',
    'main.update_existing_file',
    'main.delete_existing_file',
    'main.edit_file',
    'main.upload_files',
    'main.releases',
    'main.new_release',
    'main.release_detail',
    'main.edit_release',
    'main.delete_release_route',
    'main.upload_release_assets',
    'main.delete_release_asset',
    'main.repository_analytics',
    'main.actions_overview',
    'main.actions_run',
    'main.actions_run_action',
    'main.actions_run_logs',
    'main.actions_dispatch',
    'main.actions_secrets',
    'main.github_webhook',
    'main.notifications',
    'main.notifications_read_all',
    'main.open_notification',
    'main.notifications_unread',
    'main.security_overview',
    'main.collaborators',
    'main.collaborators_action',
    'main.accounts',
    'main.switch_account',
    'main.audit_log',
    'main.scheduled_deletions',
    'main.undo_deletion',
}


def test_create_app_uses_testing_config(app):
    assert app.config['TESTING'] is True


def test_unknown_config_name_raises():
    with pytest.raises(ValueError):
        create_app('nonexistent')


def test_production_requires_settings(monkeypatch):
    monkeypatch.setattr(ProductionConfig, 'SECRET_KEY', None)
    with pytest.raises(RuntimeError, match='SECRET_KEY'):
        create_app('production')


def test_all_endpoints_registered(app):
    endpoints = {rule.endpoint for rule in app.url_map.iter_rules()}
    assert EXPECTED_ENDPOINTS <= endpoints


def test_home_page_renders_when_logged_out(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'Login with GitHub' in response.data


@pytest.mark.parametrize('url', [
    '/github/repositories',
    '/delete_repo',
    '/repositories/some-repo/issues',
    '/repositories/some-repo/issues/1',
    '/repositories/some-repo/pull_requests',
])
def test_protected_pages_require_login(client, url):
    assert client.get(url).status_code == 403


def test_missing_private_key_raises():
    with pytest.raises(FileNotFoundError):
        load_private_key('does/not/exist.pem')
