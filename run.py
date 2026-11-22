"""run.py

Entry point for the RepoMaster web app.
Development: python run.py
Production (WSGI): point the server at run:app and set FLASK_CONFIG=production.
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])
