from flask import request, redirect, url_for, session
import requests
import os

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID") 
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
GITHUB_AUTH_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

def github_login():
    """Redirects to GitHub OAuth authorization URL"""
    redirect_url = f"{GITHUB_AUTH_URL}?client_id={CLIENT_ID}&scope=repo user"
    return redirect(redirect_url)

def github_callback():
    """Handles GitHub OAuth callback and exchanges code for access token"""
    code = request.args.get("code")  # Get the `code` from query parameters

    if code:
        # Exchange code for access token
        token_response = requests.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
            },
        )

        token_json = token_response.json()
        access_token = token_json.get("access_token")

        if access_token:
            session["github_token"] = access_token  # Save token in session
            return redirect(url_for("main_routes.show_github_repositories"))
    
    return "Failed to authenticate with GitHub.", 400
