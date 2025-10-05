import os
import logging
from dotenv import load_dotenv

# Загружаем переменные из .env файла для локальной разработки
load_dotenv()

# --- Настройки ---
MODERATOR_BOT_TOKEN = os.getenv('MODERATOR_BOT_TOKEN')
HUNTER_BOT_TOKEN = os.getenv('HUNTER_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
ADMIN_ID = os.getenv('ADMIN_ID')
DOMAIN_NAME = os.getenv('DOMAIN_NAME', 'localhost')
DB_PATH = '/app/app_data/listings.db'
SUBMISSION_COOLDOWN = 900 # 15 минут

# --- Инициализация логирования ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Проверка критически важных переменных ---
def validate_config():
    """Проверяет наличие всех обязательных переменных окружения."""
    critical_vars = {
        'MODERATOR_BOT_TOKEN': MODERATOR_BOT_TOKEN,
        'HUNTER_BOT_TOKEN': HUNTER_BOT_TOKEN,
        'CHANNEL_ID': CHANNEL_ID,
        'ADMIN_ID': ADMIN_ID
    }
    missing_vars = [name for name, value in critical_vars.items() if value is None]
    if missing_vars:
        logger.critical(f"КРИТИЧЕСКАЯ ОШИБКА: Отсутствуют переменные окружения: {', '.join(missing_vars)}. Проверьте ваш .env файл или переменные среды.")
        exit(1)
    logger.info("Конфигурация успешно загружена и проверена.")

# Выполняем проверку при импорте модуля
validate_config()