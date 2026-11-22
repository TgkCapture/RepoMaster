"""development_config.py
"""
import os
import logging
from app.config.base_config import BaseConfig


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-only-insecure-secret-key')
    LOG_LEVEL = logging.DEBUG
