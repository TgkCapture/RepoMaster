import pytest
from app import create_app, github_http, token_cache


@pytest.fixture(autouse=True)
def fresh_github_caches():
    """Installation tokens and cached GitHub responses never leak from one test into another."""
    token_cache.clear()
    github_http.clear_cache()
    yield
    token_cache.clear()
    github_http.clear_cache()


@pytest.fixture
def app(tmp_path, monkeypatch):
    # A fresh SQLite database for every test
    from app.config.testing_config import TestingConfig
    monkeypatch.setattr(TestingConfig, 'DATABASE_PATH', str(tmp_path / 'repomaster.db'))
    return create_app('testing')


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def logged_in_client(client):
    """A client whose session looks like a completed, verified GitHub sign-in."""
    with client.session_transaction() as sess:
        sess['github_user_login'] = 'alice'
        sess['github_avatar_url'] = 'https://example.com/avatar.png'
        sess['installation_id'] = 1
        sess['github_username'] = 'alice'
    return client
