"""
Handlers for the "Moderator" bot.

This module contains the Telegram bot handlers for administrative tasks,
such as viewing statistics and handling the final publication of approved
submissions.
"""
import asyncio
import json
from html import escape
from typing import Dict, Any, Optional
from datetime import datetime

import aiosqlite
import telebot.types
from telebot.types import Message

from .utils import moderator_bot, sync_moderator_bot, hunter_bot
from src import database as db
from src.config import ADMIN_ID, CHANNEL_ID, DB_PATH, logger

async def publish_listing(user_id: int, submission: Dict[str, Any]) -> None:
    """
    Handles the final publication of an approved listing to the channel.

    This function constructs the message, downloads photos from the hunter bot,
    and publishes them to the main channel. It handles single photos, media
    groups, and text-only posts.

    Args:
        user_id: The ID of the user who submitted the listing.
        submission: The submission dictionary containing all data.
    """
    logger.info(f"Starting publication process for user {user_id}.")

    submission_data = submission['data']
    submission_id = f"list_{user_id}_{int(datetime.now().timestamp())}"
    submission_data['id'] = submission_id

    rent_type = submission_data.get('rent_type', 'N/A')
    rent_type_text = "На долгий срок" if rent_type == 'long_term' else "Посуточно"
    price_suffix = "₽/мес." if rent_type == 'long_term' else "₽/сутки"

    # Sanitize all user-provided data before including it in the HTML caption
    safe_description = escape(submission_data.get('description', ''))
    safe_address = escape(submission_data.get('address', ''))
    safe_contact = escape(submission_data.get('contact', ''))
    price = escape(str(submission_data.get('price', '')))

    caption = (
        f"<b>🏠 {rent_type_text}</b>\n\n"
        f"{safe_description}\n\n"
        f"📍 <b>Адрес:</b> {safe_address}\n"
        f"💰 <b>Цена:</b> {price} {price_suffix}\n"
        f"📞 <b>Контакт:</b> {safe_contact}"
    )

    photos_ids: list[str] = submission_data.get('photos', [])
    msg: Optional[Message] = None

    try:
        if not photos_ids:
            logger.info("No photos found. Publishing text-only message.")
            msg = await moderator_bot.send_message(CHANNEL_ID, caption)
        elif len(photos_ids) == 1:
            file_id = photos_ids[0]
            logger.info(f"Processing one photo (file_id: {file_id})")
            file_info = await hunter_bot.get_file(file_id)
            file_content = await hunter_bot.download_file(file_info.file_path)
            msg = await moderator_bot.send_photo(CHANNEL_ID, file_content, caption=caption)
        else:
            logger.info(f"Processing a media group of {len(photos_ids)} photos.")
            media: list[telebot.types.InputMediaPhoto] = []
            for i, file_id in enumerate(photos_ids):
                logger.info(f"Downloading photo {i+1}/{len(photos_ids)}: {file_id}")
                file_info = await hunter_bot.get_file(file_id)
                file_content = await hunter_bot.download_file(file_info.file_path)
                media.append(
                    telebot.types.InputMediaPhoto(
                        media=file_content,
                        caption=caption if i == 0 else '',
                        parse_mode='HTML'
                    )
                )

            if media:
                logger.info("Sending media group to the channel...")
                # Use to_thread for the synchronous send_media_group call
                msgs = await asyncio.to_thread(sync_moderator_bot.send_media_group, CHANNEL_ID, media)
                msg = msgs[0] if msgs else None

        if msg:
            logger.info(f"Publication successful (message_id: {msg.message_id}). Saving to database.")
            await db.add_listing(submission_id, submission.get('type'), submission_data, msg.message_id)
            await moderator_bot.send_message(user_id, "Отлично, адрес получен! Ваше объявление опубликовано в канале.")
        else:
            raise Exception("Failed to send message to channel (message object was not received).")

    except Exception as e:
        logger.exception(f"CRITICAL ERROR during publication for user {user_id}: {e}")
        await moderator_bot.send_message(user_id, "К сожалению, при публикации вашего объявления произошла техническая ошибка. Администратор уже уведомлен.")
    finally:
        await db.clear_user_state(user_id)


def register_moderator_handlers():
    """Registers all handlers for the Moderator bot."""

    @moderator_bot.message_handler(commands=['stats'])
    async def handle_stats_command(message: Message):
        if str(message.chat.id) != str(ADMIN_ID):
            return

        try:
            stats = await db.get_db_stats()
            stat_text = (
                f"📊 <b>Статистика 'Женева'</b>\n\n"
                f"🔵 Ожидают модерации: <b>{stats['pending_count']}</b>\n"
                f"🟢 Активных объявлений: <b>{stats['active_count']}</b>\n"
                f"🗓 Опубликовано сегодня: <b>{stats['today_count']}</b>"
            )
            await moderator_bot.send_message(ADMIN_ID, stat_text)
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            await moderator_bot.send_message(ADMIN_ID, f"Ошибка при получении статистики: {e}")

    @moderator_bot.message_handler(func=lambda message: True)
    async def handle_address_and_publish(message: Message):
        user_id = message.chat.id

        # This handler should only be triggered for users in the 'pending_publication' state
        submission = await db.get_pending_publication(user_id)

        if not submission:
            # Optionally, send a message to users who send random text to this bot
            if str(user_id) == str(ADMIN_ID):
                 await moderator_bot.send_message(user_id, "Я готов к работе. Ожидаю адрес для публикации объявления.")
            return

        submission['data']['address'] = message.text
        await publish_listing(user_id, submission)

    logger.info("Handlers for the Moderator Bot have been registered.")