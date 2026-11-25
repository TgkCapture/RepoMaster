"""testing_config.py
"""
import os
import tempfile
from app.config.base_config import BaseConfig


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = 'testing-secret-key'
    GITHUB_APP_ID = '12345'
    GITHUB_APP_NAME = 'repomaster-test'
    GITHUB_PRIVATE_KEY_PATH = None
    GITHUB_CLIENT_ID = 'test-client-id'
    GITHUB_CLIENT_SECRET = 'test-client-secret'
    GITHUB_OAUTH_CALLBACK_URL = None
    LOG_FILE_PATH = os.devnull
    GITHUB_WEBHOOK_SECRET = 'test-webhook-secret'
    # The test suite's `app` fixture points this at a fresh file for every test.
    DATABASE_PATH = os.path.join(tempfile.gettempdir(), 'repomaster-test.db')
