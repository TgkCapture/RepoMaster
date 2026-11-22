"""testing_config.py
"""
import os
from app.config.base_config import BaseConfig


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = 'testing-secret-key'
    GITHUB_APP_ID = '12345'
    GITHUB_APP_NAME = 'repomaster-test'
    GITHUB_PRIVATE_KEY_PATH = None
    LOG_FILE_PATH = os.devnull
