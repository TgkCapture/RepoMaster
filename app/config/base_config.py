"""base_config.py

Settings shared by every environment. Values come from environment variables
(loaded from a local .env file when present).
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.getenv('SECRET_KEY')

    # GitHub App
    GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')
    GITHUB_APP_NAME = os.getenv('GITHUB_APP_NAME')
    GITHUB_PRIVATE_KEY_PATH = os.getenv('GITHUB_PRIVATE_KEY_PATH')

    # GitHub App user sign-in (OAuth). Found on the App's settings page.
    GITHUB_CLIENT_ID = os.getenv('GITHUB_CLIENT_ID')
    GITHUB_CLIENT_SECRET = os.getenv('GITHUB_CLIENT_SECRET')
    # Optional: full OAuth callback URL, e.g. https://example.com/github/callback.
    # Set this when running behind a proxy so the URL matches the App's Callback URL exactly.
    GITHUB_OAUTH_CALLBACK_URL = os.getenv('GITHUB_OAUTH_CALLBACK_URL')

    # Webhooks: the secret set on the GitHub App's webhook. Without it, webhook deliveries are refused.
    GITHUB_WEBHOOK_SECRET = os.getenv('GITHUB_WEBHOOK_SECRET')

    # SQLite database for notifications. Defaults to <instance folder>/repomaster.db.
    DATABASE_PATH = os.getenv('DATABASE_PATH')

    # Days a deleted repository stays archived (and can be restored) before it is really deleted.
    # 0 deletes immediately. Due deletions are run by `flask run-scheduled-deletions`.
    SOFT_DELETE_DAYS = int(os.getenv('SOFT_DELETE_DAYS') or '7')

    # Run background jobs (bulk actions) in the request instead of a background thread.
    # Only meant for tests and debugging.
    BACKGROUND_JOBS_SYNC = False

    # Largest request body accepted (file uploads). Bigger requests get 413 before being read.
    MAX_CONTENT_LENGTH = 25 * 1024 * 1024

    # Logging
    LOG_LEVEL = logging.INFO
    LOG_FILE_PATH = os.path.join('logs', 'repomaster.log')
    LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'

    @classmethod
    def setup_logging(cls):
        """Configure the root logger to write to the console and to LOG_FILE_PATH."""
        log_dir = os.path.dirname(cls.LOG_FILE_PATH) or '.'
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"Failed to create log directory: {e}")

        formatter = logging.Formatter(cls.LOG_FORMAT)

        file_handler = logging.FileHandler(cls.LOG_FILE_PATH)
        file_handler.setLevel(cls.LOG_LEVEL)
        file_handler.setFormatter(formatter)

        console_handler = logging.StreamHandler()
        console_handler.setLevel(cls.LOG_LEVEL)
        console_handler.setFormatter(formatter)

        logging.basicConfig(level=cls.LOG_LEVEL, handlers=[file_handler, console_handler])
