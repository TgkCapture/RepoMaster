"""production_config.py
"""
from app.config.base_config import BaseConfig


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    @classmethod
    def validate(cls):
        """Refuse to start in production without the required settings."""
        missing = [name for name in ('SECRET_KEY', 'GITHUB_APP_ID', 'GITHUB_APP_NAME', 'GITHUB_PRIVATE_KEY_PATH')
                   if not getattr(cls, name)]
        if missing:
            raise RuntimeError(f"Missing required environment variables for production: {', '.join(missing)}")
