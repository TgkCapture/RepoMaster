from flask import Flask
from app.routes.main_routes import main_routes
from app.config.production_config import ProductionConfig

def create_app():
    app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
    app.config.from_object(ProductionConfig)

    # Register the main_routes Blueprint
    app.register_blueprint(main_routes)

    return app



