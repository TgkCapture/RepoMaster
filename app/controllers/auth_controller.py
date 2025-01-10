from flask import redirect
import os

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID") 
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"

def github_login():
    """Redirects to GitHub OAuth authorization URL"""
    redirect_url = f"{GITHUB_AUTH_URL}?client_id={CLIENT_ID}&scope=repo user"
    return redirect(redirect_url)
