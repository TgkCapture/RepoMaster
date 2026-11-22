"""Configuration classes, selected by name via the FLASK_CONFIG environment variable."""
from app.config.development_config import DevelopmentConfig
from app.config.production_config import ProductionConfig
from app.config.testing_config import TestingConfig

config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}
