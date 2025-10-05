"""
Bot Utilities Module.

This module initializes and provides centralized access to the Telegram bot instances.
This helps prevent circular dependencies between the bot handler modules.
"""
import telebot
from telebot.async_telebot import AsyncTeleBot

from src.config import MODERATOR_BOT_TOKEN, HUNTER_BOT_TOKEN

# --- Bot Instances ---

# It's important to assert that tokens are not None, as the config module
# only logs a critical error and exits. This provides a clearer static check.
assert MODERATOR_BOT_TOKEN is not None, "MODERATOR_BOT_TOKEN is not set in environment."
assert HUNTER_BOT_TOKEN is not None, "HUNTER_BOT_TOKEN is not set in environment."

# Asynchronous bot instances for primary operations
moderator_bot: AsyncTeleBot = AsyncTeleBot(MODERATOR_BOT_TOKEN, parse_mode='HTML')
hunter_bot: AsyncTeleBot = AsyncTeleBot(HUNTER_BOT_TOKEN, parse_mode='HTML')

# Synchronous instance for operations not fully supported in async mode,
# such as sending media groups with in-memory file content.
# This should only be used with `asyncio.to_thread`.
sync_moderator_bot: telebot.TeleBot = telebot.TeleBot(MODERATOR_BOT_TOKEN, parse_mode='HTML')