"""
Request handler functions for the aiohttp web server.

This module defines the logic for all API endpoints and for serving
static frontend files like the admin panel and the public map.
"""
import json
from html import escape
from typing import Dict, Any

from aiohttp import web

from src import database as db
from src.config import logger, CHANNEL_ID, ADMIN_ID
from src.bots.utils import hunter_bot, moderator_bot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- API Handlers ---

async def get_stats(request: web.Request) -> web.Response:
    """
    Handles requests for application statistics.

    Fetches counts of pending, active, and today's listings from the database.

    Returns:
        A JSON response with the statistics.
    """
    try:
        stats = await db.get_db_stats()
        return web.json_response(stats)
    except Exception as e:
        logger.exception(f"API Error at /api/stats: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_submissions(request: web.Request) -> web.Response:
    """
    Fetches all submissions currently pending moderation.

    Returns:
        A JSON response containing a dictionary of submission objects.
    """
    try:
        submissions = await db.get_all_submissions()
        return web.json_response(submissions)
    except Exception as e:
        logger.exception(f"API Error at /api/submissions: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_listings(request: web.Request) -> web.Response:
    """
    Fetches all published rental offer listings for the public map.

    Returns:
        A JSON response containing a dictionary of listing objects.
    """
    try:
        listings = await db.get_rent_offer_listings()
        return web.json_response(listings)
    except Exception as e:
        logger.exception(f"API Error at /api/listings: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_image(request: web.Request) -> web.Response:
    """
    Serves an image from Telegram by its file_id.

    The file_id is extracted from the request URL.

    Returns:
        A web.Response with the image content and JPEG content type.
    """
    file_id = request.match_info.get('file_id')
    if not file_id:
        return web.Response(status=404, text="File ID is missing.")
    try:
        file_info = await hunter_bot.get_file(file_id)
        # The file path from get_file is temporary, so we must download it immediately
        file_content = await hunter_bot.download_file(file_info.file_path)
        return web.Response(body=file_content, content_type='image/jpeg')
    except Exception as e:
        logger.error(f"Error fetching image for file_id {file_id}: {e}")
        return web.Response(status=500, text="Error retrieving image.")

async def approve_submission(request: web.Request) -> web.Response:
    """
    Handles the approval of a submission from the admin panel.
    """
    try:
        data = await request.json()
        submission_id = data.get('id')
        if not submission_id:
            return web.json_response({'status': 'error', 'message': 'Submission ID is required'}, status=400)

        logger.info(f"Received APPROVE command for submission ID: {submission_id}")

        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            # Use a transaction to ensure atomicity
            async with conn.begin():
                cursor = await conn.execute("SELECT submission_type, data FROM submissions WHERE submission_id=?", (submission_id,))
                row = await cursor.fetchone()

                if not row:
                    logger.warning(f"Submission {submission_id} not found for approval.")
                    return web.json_response({'status': 'error', 'message': 'Submission not found'}, status=404)

                sub_type, sub_data_json = row
                sub_data = json.loads(sub_data_json)
                user_id = sub_data.get('author_id')

                await db.delete_submission(conn, submission_id)

                if sub_type.startswith('rent_offer'):
                    await db.move_submission_to_pending(conn, user_id, sub_type, sub_data_json)
                    await moderator_bot.send_message(user_id, "🎉 Ваше объявление одобрено! Остался последний шаг: пожалуйста, пришлите точный адрес объекта (Город, Улица, Дом), чтобы мы могли добавить его на карту.")

                elif sub_type == 'rent_request':
                    text = (f"<b>🔍 Ищу жильё</b>\n\n"
                            f"{escape(sub_data.get('description'))}\n\n"
                            f"<b>👤 Автор:</b> @{escape(sub_data.get('author_username') or 'скрыт')}")
                    msg = await moderator_bot.send_message(CHANNEL_ID, text)
                    await db.add_listing(submission_id, sub_type, sub_data, msg.message_id)
                    await moderator_bot.send_message(user_id, "Ваша заявка на поиск одобрена и опубликована в канале!")

        logger.info(f"Submission {submission_id} approved successfully.")
        return web.json_response({'status': 'ok'})

    except Exception as e:
        logger.exception(f"CRITICAL ERROR during submission approval: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def reject_submission(request: web.Request) -> web.Response:
    """
    Handles the rejection of a submission from the admin panel.
    """
    try:
        data = await request.json()
        submission_id = data.get('id')
        reason = data.get('reason', 'Причина не указана.')
        if not submission_id:
            return web.json_response({'status': 'error', 'message': 'Submission ID is required'}, status=400)

        logger.info(f"Received REJECT command for ID: {submission_id} with reason: {reason}")

        async with db.aiosqlite.connect(db.DB_PATH) as conn:
            cursor = await conn.execute("SELECT data FROM submissions WHERE submission_id=?", (submission_id,))
            row = await cursor.fetchone()
            if not row:
                return web.json_response({'status': 'error', 'message': 'Submission not found'}, status=404)

            user_id = json.loads(row[0]).get('author_id')
            await db.delete_submission(conn, submission_id)
            await conn.commit()

        if user_id:
            try:
                await moderator_bot.send_message(user_id, f"К сожалению, ваша заявка была отклонена модератором.\n\n<i>Причина: {escape(reason)}</i>")
            except Exception as e:
                logger.warning(f"Failed to notify user {user_id} of rejection: {e}")

        logger.info(f"Submission {submission_id} successfully rejected.")
        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.exception(f"CRITICAL ERROR during submission rejection: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)


# --- Static File Handlers ---

async def serve_admin_panel(request: web.Request) -> web.FileResponse:
    """Serves the admin_panel.html file."""
    return web.FileResponse('./admin_panel.html')

async def serve_public_map(request: web.Request) -> web.FileResponse:
    """Serves the public_map.html file."""
    return web.FileResponse('./public_map.html')