import telebot
from telebot.async_telebot import AsyncTeleBot
from src.config import MODERATOR_BOT_TOKEN, HUNTER_BOT_TOKEN

# --- Инициализация ботов ---
# Асинхронные экземпляры для основной работы
moderator_bot = AsyncTeleBot(MODERATOR_BOT_TOKEN, parse_mode='HTML')
hunter_bot = AsyncTeleBot(HUNTER_BOT_TOKEN, parse_mode='HTML')

# Синхронный экземпляр для операций, которые пока не полностью поддерживаются в async,
# например, отправка медиа-групп с file_content.
# Важно: используется ТОЛЬКО для специфических задач через asyncio.to_thread
sync_moderator_bot = telebot.TeleBot(MODERATOR_BOT_TOKEN, parse_mode='HTML')