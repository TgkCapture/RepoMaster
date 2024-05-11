# development_config.py

from dotenv import load_dotenv
import os

load_dotenv()

class DevelopmentConfig:
    DEBUG = True
    SECRET_KEY = 'your_secret_key'

    CLIENT_ID = os.getenv('consumer_key')
    CLIENT_KEY = os.getenv('consumer_secret')