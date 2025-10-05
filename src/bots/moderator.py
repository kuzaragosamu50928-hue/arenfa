import asyncio
import json
from html import escape
import telebot.types
import aiosqlite

from .utils import moderator_bot, sync_moderator_bot, hunter_bot
from src.database import add_listing, clear_user_state
from src.config import ADMIN_ID, CHANNEL_ID, DB_PATH, logger

async def publish_listing(user_id, submission):
    """Основная логика публикации объявления в канал."""
    logger.info(f"Начинаю процесс публикации для пользователя {user_id}.")

    submission_data = submission['data']
    submission_id = f"list_{user_id}_{int(asyncio.to_thread(lambda: __import__('datetime').datetime.now().timestamp()))}"
    submission_data['id'] = submission_id

    rent_type = submission_data.get('rent_type')
    rent_type_text = "На долгий срок" if rent_type == 'long_term' else "Посуточно"
    price_suffix = "₽/мес." if rent_type == 'long_term' else "₽/сутки"

    caption = (
        f"<b>🏠 {rent_type_text}</b>\n\n"
        f"{escape(submission_data.get('description', ''))}\n\n"
        f"📍 <b>Адрес:</b> {escape(submission_data.get('address', ''))}\n"
        f"💰 <b>Цена:</b> {submission_data.get('price', '')} {price_suffix}\n"
        f"📞 <b>Контакт:</b> {escape(submission_data.get('contact', ''))}"
    )

    photos_ids = submission_data.get('photos', [])
    msg = None

    try:
        if not photos_ids:
            logger.info("Фото нет. Публикую только текст.")
            msg = await moderator_bot.send_message(CHANNEL_ID, caption)
        elif len(photos_ids) == 1:
            file_id = photos_ids[0]
            logger.info(f"Обрабатываю одно фото (file_id: {file_id})")
            file_info = await hunter_bot.get_file(file_id)
            file_content = await hunter_bot.download_file(file_info.file_path)
            msg = await moderator_bot.send_photo(CHANNEL_ID, file_content, caption=caption)
        else:
            logger.info(f"Обрабатываю группу из {len(photos_ids)} фото.")
            media = []
            for i, file_id in enumerate(photos_ids):
                logger.info(f"Скачиваю фото {i+1}/{len(photos_ids)}: {file_id}")
                file_info = await hunter_bot.get_file(file_id)
                file_content = await hunter_bot.download_file(file_info.file_path)
                # Первый элемент медиа-группы несет подпись
                media.append(telebot.types.InputMediaPhoto(file_content, caption=caption if i == 0 else '', parse_mode='HTML'))

            if media:
                logger.info("Отправляю медиа-группу в канал...")
                # Используем to_thread для неблокирующего вызова синхронной функции
                msgs = await asyncio.to_thread(sync_moderator_bot.send_media_group, CHANNEL_ID, media)
                msg = msgs[0] if msgs else None

        if msg:
            logger.info(f"Публикация в канале УСПЕШНА (message_id: {msg.message_id}). Сохраняю в базу.")
            await add_listing(submission_id, submission.get('type'), submission_data, msg.message_id)
            await moderator_bot.send_message(user_id, "Отлично, адрес получен! Ваше объявление опубликовано в канале.")
        else:
            raise Exception("Не удалось отправить сообщение в канал (объект сообщения не был получен).")

    except Exception as e:
        logger.exception(f"КРИТИЧЕСКАЯ ОШИБКА на этапе публикации от {user_id}: {e}")
        await moderator_bot.send_message(user_id, "К сожалению, при публикации вашего объявления произошла техническая ошибка. Администратор уже уведомлен.")
    finally:
        await clear_user_state(user_id)


def register_moderator_handlers():
    """Регистрирует все обработчики для бота-модератора."""

    @moderator_bot.message_handler(commands=['stats'])
    async def handle_stats_command(message):
        if str(message.chat.id) != str(ADMIN_ID):
            return

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute("SELECT COUNT(*) FROM submissions") as cursor:
                    pending_count = (await cursor.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM listings") as cursor:
                    active_count = (await cursor.fetchone())[0]
                async with db.execute("SELECT COUNT(*) FROM listings WHERE date(published_at) = date('now')") as cursor:
                    today_count = (await cursor.fetchone())[0]

            stat_text = (
                f"📊 <b>Статистика 'Женева'</b>\n\n"
                f"🔵 Ожидают модерации: <b>{pending_count}</b>\n"
                f"🟢 Активных объявлений: <b>{active_count}</b>\n"
                f"🗓 Опубликовано сегодня: <b>{today_count}</b>"
            )
            await moderator_bot.send_message(ADMIN_ID, stat_text)
        except Exception as e:
            await moderator_bot.send_message(ADMIN_ID, f"Ошибка при получении статистики: {e}")

    @moderator_bot.message_handler(func=lambda message: True)
    async def handle_address_and_publish(message):
        user_id = message.chat.id
        submission = None

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT submission_type, data FROM pending_publication WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    submission = {'type': row[0], 'data': json.loads(row[1])}
                    await db.execute("DELETE FROM pending_publication WHERE user_id=?", (user_id,))
                    await db.commit()

        if not submission:
            return

        submission['data']['address'] = message.text
        await publish_listing(user_id, submission)

    logger.info("Обработчики бота-модератора зарегистрированы.")