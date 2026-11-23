import pytest
from app import create_app


@pytest.fixture
def app():
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
