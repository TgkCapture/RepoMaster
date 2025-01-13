# github_app_config.py

from flask import Flask
import os
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

GITHUB_APP_ID = os.getenv('GITHUB_APP_ID')
GITHUB_PRIVATE_KEY = os.getenv('GITHUB_PRIVATE_KEY')