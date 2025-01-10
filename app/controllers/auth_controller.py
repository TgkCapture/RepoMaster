from flask import Blueprint, request, redirect, url_for, session
import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID") 
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"

auth_routes = Blueprint('auth_routes', __name__)

def github_login():
    """Redirects to GitHub OAuth authorization URL"""
    redirect_url = f"{GITHUB_AUTH_URL}?client_id={CLIENT_ID}&scope=repo user"
    return redirect(redirect_url)