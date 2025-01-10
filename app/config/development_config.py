import os
from dotenv import load_dotenv
import logging

load_dotenv()

class DevelopmentConfig:
    DEBUG = True
    SECRET_KEY = 'your_secret_key'

    CLIENT_ID = os.getenv('GITHUB_CONSUMER_KEY')
    CLIENT_SECRET = os.getenv('GITHUB_CONSUMER_SECRET')  # Updated for consistency

    # Logging Configurations
    LOG_LEVEL = logging.DEBUG
    LOG_FILE_PATH = os.path.join('logs', 'repomaster.log')
    LOG_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'

    @staticmethod
    def setup_logging():
        log_dir = os.path.dirname(DevelopmentConfig.LOG_FILE_PATH)
        
        # Ensure the logging directory is valid
        if not log_dir:
            log_dir = '.'  # Default to current directory
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"Failed to create log directory: {e}")

        # Set up the file handler
        file_handler = logging.FileHandler(DevelopmentConfig.LOG_FILE_PATH)
        file_handler.setLevel(DevelopmentConfig.LOG_LEVEL)
        file_handler.setFormatter(logging.Formatter(DevelopmentConfig.LOG_FORMAT))

        # Set up the console handler (optional)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(DevelopmentConfig.LOG_LEVEL)
        console_handler.setFormatter(logging.Formatter(DevelopmentConfig.LOG_FORMAT))

        # Configure the root logger
        logging.basicConfig(level=DevelopmentConfig.LOG_LEVEL, handlers=[file_handler, console_handler])
