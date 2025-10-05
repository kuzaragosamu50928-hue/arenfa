"""
Configuration module for the Geneva project.

This module loads all necessary configuration from environment variables.
It uses python-dotenv to load a .env file for local development.
It also provides a centralized logger and validates the presence of
critical environment variables upon import.
"""
import os
import logging
from typing import Optional
# Attempt to load .env file for local development.
# In a container, environment variables are injected directly.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # This is expected in a production container where python-dotenv is not installed.
    # The application will rely on environment variables provided by Docker/the system.
    pass

# --- Telegram Bot Tokens ---
MODERATOR_BOT_TOKEN: Optional[str] = os.getenv('MODERATOR_BOT_TOKEN')
HUNTER_BOT_TOKEN: Optional[str] = os.getenv('HUNTER_BOT_TOKEN')

# --- Telegram Channel/Admin Info ---
CHANNEL_ID: Optional[str] = os.getenv('CHANNEL_ID')
ADMIN_ID: Optional[str] = os.getenv('ADMIN_ID')

# --- Web & Database Settings ---
DOMAIN_NAME: str = os.getenv('DOMAIN_NAME', 'localhost')
DB_PATH: str = '/app/app_data/listings.db'
SUBMISSION_COOLDOWN: int = 900  # Cooldown period in seconds (15 minutes)

# --- Logging Initialization ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Critical Configuration Validation ---
def validate_config() -> None:
    """
    Validates that all essential environment variables are set.

    Raises:
        SystemExit: If any critical environment variables are missing.
    """
    critical_vars = {
        'MODERATOR_BOT_TOKEN': MODERATOR_BOT_TOKEN,
        'HUNTER_BOT_TOKEN': HUNTER_BOT_TOKEN,
        'CHANNEL_ID': CHANNEL_ID,
        'ADMIN_ID': ADMIN_ID
    }
    missing_vars = [name for name, value in critical_vars.items() if not value]

    if missing_vars:
        logger.critical(
            f"CRITICAL ERROR: Missing environment variables: {', '.join(missing_vars)}. "
            "Please check your .env file or environment settings."
        )
        exit(1)

    logger.info("Configuration successfully loaded and validated.")

# Perform validation when the module is imported.
validate_config()