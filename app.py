# app.py
from flask import Flask
from app.routes.main_routes import main_routes
from app.config.production_config import ProductionConfig

app = Flask(__name__, template_folder='app/templates')
app.config.from_object(ProductionConfig)

# Register the main_routes Blueprint
app.register_blueprint(main_routes)

if __name__ == '__main__':
    app.run(debug=False)
