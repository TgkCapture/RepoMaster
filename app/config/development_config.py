# development_config.py

import os
from dotenv import load_dotenv

load_dotenv()

class DevelopmentConfig:
    DEBUG = True
    SECRET_KEY = 'your_secret_key'

    CLIENT_ID = os.getenv('GITHUB_CONSUMER_KEY'),
    CLIENT_KEY = os.getenv('GITHUB_CONSUMER_SECRET')