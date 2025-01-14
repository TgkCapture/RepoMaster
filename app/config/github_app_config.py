# github_app_config.py

from flask import Flask
import os
import logging
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

logging.basicConfig(level=logging.INFO)

GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')

def load_private_key():
    private_key_path = os.getenv('GITHUB_PRIVATE_KEY_PATH')
    if private_key_path and os.path.exists(private_key_path):
        with open(private_key_path, 'r') as f:
            private_key = f.read()
            logging.info(f"Private key loaded successfully. Preview: {private_key[:20]}...{private_key[-20:]}")
            return private_key
    else:
        raise FileNotFoundError(f"Private key file not found at {private_key_path}")

# Load the private key
GITHUB_PRIVATE_KEY = load_private_key()