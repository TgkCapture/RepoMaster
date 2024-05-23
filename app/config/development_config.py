import os
from dotenv import load_dotenv
import logging

load_dotenv()

class DevelopmentConfig:
    DEBUG = True
    SECRET_KEY = 'your_secret_key'

    CLIENT_ID = os.getenv('GITHUB_CONSUMER_KEY')
    CLIENT_KEY = os.getenv('GITHUB_CONSUMER_SECRET')

    # Logging Configurations
    LOG_LEVEL = logging.DEBUG
    LOG_FILE_PATH = os.path.join('logs', 'repomaster.log')
    LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'

    @staticmethod
    def setup_logging():
        
        log_dir = os.path.dirname(DevelopmentConfig.LOG_FILE_PATH)
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"Failed to create log directory: {e}")

        logging.basicConfig(
            level=DevelopmentConfig.LOG_LEVEL,
            format=DevelopmentConfig.LOG_FORMAT,
            filename=DevelopmentConfig.LOG_FILE_PATH
        )
