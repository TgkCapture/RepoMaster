from flask import render_template, request
import logging

def register_error_handlers(app):
    @app.errorhandler(404)
    def page_not_found(e):
        """Custom 404 error handler."""
        logging.error(f"404 error: {request.url} not found.")
        return render_template('errors/404.html', error_message="Page not found"), 404
