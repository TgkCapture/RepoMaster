from flask import Flask
from flask_oauthlib.client import OAuth
import os
from dotenv import load_dotenv

app = Flask(__name__)

load_dotenv()

oauth = OAuth(app)

github = oauth.remote_app(
    'github',
    consumer_key= os.getenv('GITHUB_CONSUMER_KEY'),  
    consumer_secret= os.getenv('GITHUB_CONSUMER_SECRET'),  
    request_token_params = {'scope': 'user:email, public_repo, repo, user'},
    base_url='https://api.github.com/',
    request_token_url=None,
    access_token_method='POST',
    access_token_url='https://github.com/login/oauth/access_token',
    authorize_url='https://github.com/login/oauth/authorize',
)
