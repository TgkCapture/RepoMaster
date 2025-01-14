import os
from dotenv import load_dotenv
import logging

load_dotenv()

class DevelopmentConfig:
    DEBUG = True
    SECRET_KEY = 'your_secret_key'

    CLIENT_ID = os.getenv('GITHUB_CONSUMER_KEY')
    CLIENT_SECRET = os.getenv('GITHUB_CONSUMER_SECRET')  

    # Logging Configurations
    LOG_LEVEL = logging.DEBUG
    LOG_FILE_PATH = os.path.join('logs', 'repomaster.log')
    LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'

    @staticmethod
    def setup_logging():
        log_dir = os.path.dirname(DevelopmentConfig.LOG_FILE_PATH)
              
        if not log_dir:
            log_dir = '.' 
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"Failed to create log directory: {e}")

        file_handler = logging.FileHandler(DevelopmentConfig.LOG_FILE_PATH)
        file_handler.setLevel(DevelopmentConfig.LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter(DevelopmentConfig.LOG_FORMAT))

        console_handler = logging.StreamHandler()
        console_handler.setLevel(DevelopmentConfig.LOG_LEVEL)
        console_handler.setFormatter(logging.Formatter(DevelopmentConfig.LOG_FORMAT))

        # Configure the root logger
        logging.basicConfig(level=DevelopmentConfig.LOG_LEVEL, handlers=[file_handler, console_handler])
