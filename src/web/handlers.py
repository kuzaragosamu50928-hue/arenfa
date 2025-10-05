import json
import aiosqlite
from html import escape
from aiohttp import web

from src.config import DB_PATH, logger, CHANNEL_ID
from src.bots.utils import hunter_bot, moderator_bot

# --- API хендлеры ---

async def get_stats(request):
    """Возвращает статистику по заявкам и объявлениям."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT COUNT(*) FROM submissions") as cursor:
                pending_count = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM listings") as cursor:
                active_count = (await cursor.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM listings WHERE date(published_at) = date('now')") as cursor:
                today_count = (await cursor.fetchone())[0]
        return web.json_response({
            'pending_count': pending_count,
            'active_count': active_count,
            'today_count': today_count
        })
    except Exception as e:
        logger.exception(f"Ошибка API /api/stats: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_submissions(request):
    """Возвращает список заявок, ожидающих модерации."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT submission_id, submission_type, data FROM submissions ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            submissions = {row[0]: {'type': row[1], 'data': json.loads(row[2])} for row in rows}
        return web.json_response(submissions)
    except Exception as e:
        logger.exception(f"Ошибка API /api/submissions: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_listings(request):
    """Возвращает список опубликованных объявлений о сдаче."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT submission_id, listing_type, data FROM listings WHERE listing_type LIKE 'rent_offer_%'")
            rows = await cursor.fetchall()
            listings = {row[0]: {'type': row[1], 'data': json.loads(row[2])} for row in rows}
        return web.json_response(listings)
    except Exception as e:
        logger.exception(f"Ошибка API /api/listings: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_image(request):
    """Отдает файл изображения по его file_id."""
    file_id = request.match_info.get('file_id')
    if not file_id:
        return web.Response(status=404)
    try:
        file_info = await hunter_bot.get_file(file_id)
        file_content = await hunter_bot.download_file(file_info.file_path)
        return web.Response(body=file_content, content_type='image/jpeg')
    except Exception as e:
        logger.error(f"Ошибка при получении фото {file_id}: {e}")
        return web.Response(status=500)

async def approve_submission(request):
    """Обрабатывает одобрение заявки."""
    data = await request.json()
    submission_id = data.get('id')
    logger.info(f"Получена команда ОДОБРИТЬ для ID: {submission_id}")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT submission_type, data FROM submissions WHERE submission_id=?", (submission_id,))
            row = await cursor.fetchone()
            if not row:
                logger.warning(f"Заявка {submission_id} НЕ НАЙДЕНА в submissions.")
                return web.json_response({'status': 'error', 'message': 'Submission not found'}, status=404)

            submission_type, submission_data_json = row
            submission_data = json.loads(submission_data_json)
            user_id = submission_data.get('author_id')

            await db.execute("DELETE FROM submissions WHERE submission_id=?", (submission_id,))

            if submission_type.startswith('rent_offer'):
                await db.execute("INSERT OR REPLACE INTO pending_publication (user_id, submission_type, data) VALUES (?, ?, ?)",
                                 (user_id, submission_type, submission_data_json))
                await moderator_bot.send_message(user_id, "🎉 Ваше объявление одобрено! Остался последний шаг: пожалуйста, пришлите точный адрес объекта (Город, Улица, Дом), чтобы мы могли добавить его на карту.")
            elif submission_type == 'rent_request':
                text = (f"<b>🔍 Ищу жильё</b>\n\n"
                        f"{escape(submission_data.get('description'))}\n\n"
                        f"<b>👤 Автор:</b> @{escape(submission_data.get('author_username') or 'скрыт')}")
                msg = await moderator_bot.send_message(CHANNEL_ID, text)
                await db.execute("INSERT INTO listings (submission_id, listing_type, data, message_id) VALUES (?, ?, ?, ?)",
                                 (submission_id, submission_type, submission_data_json, msg.message_id))
                await moderator_bot.send_message(user_id, "Ваша заявка на поиск одобрена и опубликована в канале!")

            await db.commit()
        logger.info(f"Заявка {submission_id} успешно одобрена.")
        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.exception(f"КРИТИЧЕСКАЯ ОШИБКА при ОДОБРЕНИИ заявки {submission_id}: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def reject_submission(request):
    """Обрабатывает отклонение заявки."""
    data = await request.json()
    submission_id = data.get('id')
    reason = data.get('reason', 'Причина не указана.')
    logger.info(f"Получена команда ОТКЛОНИТЬ для ID: {submission_id} с причиной: {reason}")
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT data FROM submissions WHERE submission_id=?", (submission_id,))
            row = await cursor.fetchone()
            if not row:
                return web.json_response({'status': 'error', 'message': 'Submission not found'}, status=404)

            user_id = json.loads(row[0]).get('author_id')
            await db.execute("DELETE FROM submissions WHERE submission_id=?", (submission_id,))
            await db.commit()

        if user_id:
            try:
                await moderator_bot.send_message(user_id, f"К сожалению, ваша заявка была отклонена модератором.\n\n<i>Причина: {escape(reason)}</i>")
            except Exception as e:
                logger.warning(f"Не удалось уведомить пользователя {user_id} об отклонении: {e}")

        logger.info(f"Заявка {submission_id} успешно отклонена.")
        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.exception(f"КРИТИЧЕСКАЯ ОШИБКА при ОТКЛОНЕНИИ заявки {submission_id}: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

# --- Хендлеры для статических файлов ---

async def serve_admin_panel(request):
    """Отдает HTML-страницу админ-панели."""
    return web.FileResponse('./admin_panel.html')

# В будущем здесь может быть публичная карта
async def serve_public_map(request):
    """Отдает HTML-страницу публичной карты."""
    # Для этого примера, предположим, что public_map.html не существует,
    # и мы можем просто перенаправить на админ-панель или показать заглушку.
    # В реальном проекте здесь был бы свой файл.
    # return web.FileResponse('./public_map.html')
    return web.HTTPFound('/admin')