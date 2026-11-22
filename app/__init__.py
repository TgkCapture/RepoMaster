"""RepoMaster application factory."""
import os
from flask import Flask
from app.config import config_by_name


def create_app(config_name=None):
    """
    Create and configure the Flask application.

    config_name: 'development', 'production' or 'testing'.
    Defaults to the FLASK_CONFIG environment variable, then 'development'.
    """
    config_name = config_name or os.getenv('FLASK_CONFIG', 'development')
    if config_name not in config_by_name:
        raise ValueError(f"Unknown FLASK_CONFIG '{config_name}'. Expected one of: {', '.join(config_by_name)}")
    config_class = config_by_name[config_name]

    if hasattr(config_class, 'validate'):
        config_class.validate()

    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.setup_logging()

    from app.routes import main_routes
    app.register_blueprint(main_routes)

    return app
