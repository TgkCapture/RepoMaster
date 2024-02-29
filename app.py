# app.py
from flask import Flask
from app.config.oauth_config import oauth
from app.routes.main_routes import main_routes
from app.config.development_config import DevelopmentConfig

app = Flask(__name__, template_folder='app/templates')
app.config.from_object(DevelopmentConfig)

oauth.init_app(app)

# Register the main_routes Blueprint
app.register_blueprint(main_routes)

if __name__ == '__main__':
    app.run(debug=True)
