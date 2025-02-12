# app.py
from flask import Flask
import os
from app.routes.main_routes import main_routes
from app.config.development_config import DevelopmentConfig

app = Flask(__name__, template_folder='app/templates', static_folder='app/static')
app.config.from_object(DevelopmentConfig)

DevelopmentConfig.setup_logging()

app.register_blueprint(main_routes)

if __name__ == '__main__':
    app.run(debug=True)