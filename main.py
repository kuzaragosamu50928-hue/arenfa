# -*- coding: utf-8 -*-
import asyncio
import sqlite3
import json
import logging
import os
import signal
from datetime import datetime
from html import escape
from aiohttp import web
import telebot
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ ---
MODERATOR_BOT_TOKEN = os.getenv('MODERATOR_BOT_TOKEN')
HUNTER_BOT_TOKEN = os.getenv('HUNTER_BOT_TOKEN')
CHANNEL_ID = os.getenv('CHANNEL_ID')
ADMIN_ID = os.getenv('ADMIN_ID')
DOMAIN_NAME = os.getenv('DOMAIN_NAME', 'localhost')
DB_PATH = '/app/app_data/listings.db'
SUBMISSION_COOLDOWN = 900 # 15 минут

# --- ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

moderator_bot = AsyncTeleBot(MODERATOR_BOT_TOKEN, parse_mode='HTML')
hunter_bot = AsyncTeleBot(HUNTER_BOT_TOKEN, parse_mode='HTML')
sync_bot = telebot.TeleBot(MODERATOR_BOT_TOKEN)

# --- РАБОТА С БАЗОЙ ДАННЫХ ---
def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_sessions (user_id INTEGER PRIMARY KEY, step TEXT NOT NULL, data TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS submissions (id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT UNIQUE NOT NULL, submission_type TEXT NOT NULL, data TEXT NOT NULL, user_id INTEGER, created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS pending_publication (user_id INTEGER PRIMARY KEY, submission_type TEXT NOT NULL, data TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS listings (id INTEGER PRIMARY KEY AUTOINCREMENT, submission_id TEXT UNIQUE NOT NULL, listing_type TEXT NOT NULL, data TEXT NOT NULL, message_id INTEGER, published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()
        logger.info("База данных 'Женева' успешно инициализирована.")

def get_user_state(user_id):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT step, data FROM user_sessions WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row: return {'step': row[0], 'data': json.loads(row[1])}
    except Exception as e:
        logger.error(f"Ошибка при получении состояния пользователя {user_id}: {e}")
    return None

def set_user_state(user_id, step, data):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_sessions (user_id, step, data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                       (user_id, step, json.dumps(data, ensure_ascii=False)))
        conn.commit()

def clear_user_state(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.commit()

async def save_submission_to_db(submission_id, submission_type, data, user_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO submissions (submission_id, submission_type, data, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
                       (submission_id, submission_type, json.dumps(data, ensure_ascii=False), user_id, datetime.now()))
        conn.commit()
    if ADMIN_ID:
        try:
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("Перейти в админ-панель", url=f"http://{DOMAIN_NAME}/admin"))
            await moderator_bot.send_message(ADMIN_ID, "🛎️ Новая заявка на модерацию!", reply_markup=markup)
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {ADMIN_ID}: {e}")

# --- ЛОГИКА БОТА-ОХОТНИКА ---
@hunter_bot.message_handler(commands=['start'])
async def handle_start(message):
    user_id = message.chat.id
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT created_at FROM submissions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,))
        row = cursor.fetchone()
        if row:
            try:
                last_submission_time = datetime.fromisoformat(row[0])
                if (datetime.now() - last_submission_time).total_seconds() < SUBMISSION_COOLDOWN:
                    await hunter_bot.send_message(user_id, f"⏳ Вы слишком часто подаете объявления. Пожалуйста, подождите еще несколько минут.")
                    return
            except (ValueError, TypeError):
                 logger.warning(f"Не удалось распознать формат даты: {row[0]}")

    clear_user_state(user_id)
    set_user_state(user_id, 'start', {})
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton('🏠 Сдать жильё', callback_data='action_offer'))
    markup.add(InlineKeyboardButton('🔍 Ищу жильё', callback_data='action_request'))
    await hunter_bot.send_message(user_id, "Здравствуйте! Я помогу вам сдать или найти жильё в Мелитополе.\n\nЧто вы хотите сделать?", reply_markup=markup)

@hunter_bot.callback_query_handler(func=lambda call: call.data.startswith('action_'))
async def handle_action_choice(call):
    user_id = call.message.chat.id
    action = call.data.split('_')[1]
    if action == 'offer':
        set_user_state(user_id, 'offer_type', {'type': 'rent_offer'})
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(InlineKeyboardButton('🗓 На долгий срок', callback_data='type_long_term'),
                   InlineKeyboardButton('☀️ Посуточно', callback_data='type_daily'))
        await hunter_bot.edit_message_text("Отлично! Вы хотите сдать жильё на долгий срок или посуточно?", user_id, call.message.message_id, reply_markup=markup)
    elif action == 'request':
        set_user_state(user_id, 'request_description', {'type': 'rent_request'})
        await hunter_bot.edit_message_text("Понимаю. Опишите в одном сообщении, какое жильё вы ищете (район, кол-во комнат, бюджет и т.д.). Эту заявку увидят собственники.", user_id, call.message.message_id)

@hunter_bot.callback_query_handler(func=lambda call: call.data.startswith('type_'))
async def handle_offer_type(call):
    user_id = call.message.chat.id
    rent_type = call.data.replace('type_', '')
    state = get_user_state(user_id)
    if not state: return
    state['data']['rent_type'] = rent_type
    set_user_state(user_id, 'offer_description', state['data'])
    await hunter_bot.edit_message_text("Теперь, пожалуйста, напишите подробное описание вашего жилья: кол-во комнат, адрес, состояние, мебель, техника и т.д. Вся информация в одном сообщении.", user_id, call.message.message_id)

async def process_text_input(message, current_step_name, next_step, prompt):
    user_id = message.chat.id
    state = get_user_state(user_id)
    if not (state and state['step'] == current_step_name): return
    state['data'][current_step_name.replace('offer_', '')] = message.text
    set_user_state(user_id, next_step, state['data'])
    await hunter_bot.send_message(user_id, prompt)

@hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_description')
async def handle_offer_description(message):
    state = get_user_state(message.chat.id)
    if not state: return
    rent_type = state['data'].get('rent_type')
    price_question = "Укажите цену в рублях за месяц." if rent_type == 'long_term' else "Укажите цену в рублях за сутки."
    await process_text_input(message, 'offer_description', 'offer_price', f"Отлично. {price_question} Просто напишите число.")

@hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_price')
async def handle_offer_price(message):
    if message.text.isdigit():
        state = get_user_state(message.chat.id)
        if not state: return
        state['data']['price'] = int(message.text)
        state['data']['photos'] = []
        set_user_state(message.chat.id, 'offer_photos', state['data'])
        await hunter_bot.send_message(message.chat.id, "Понял. Теперь отправьте, пожалуйста, ваше лучшее фото. Позже можно будет добавить еще.")
    else:
        await hunter_bot.send_message(message.chat.id, "Пожалуйста, введите цену цифрами, без других символов.")

@hunter_bot.message_handler(content_types=['photo'], func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_photos')
async def handle_offer_photos(message):
    user_id = message.chat.id
    state = get_user_state(user_id)
    if not state: return

    state['data']['photos'].append(message.photo[-1].file_id)
    set_user_state(user_id, 'offer_photos', state['data'])

    markup = InlineKeyboardMarkup(row_width=2)
    finish_button = InlineKeyboardButton("✅ Завершить", callback_data="photos_done")
    
    if len(state['data']['photos']) < 5:
        add_more_button = InlineKeyboardButton("➕ Добавить еще", callback_data="add_more_photos")
        markup.add(add_more_button, finish_button)
        await hunter_bot.send_message(user_id, f"Фото {len(state['data']['photos'])}/5 добавлено. Хотите добавить еще или завершить?", reply_markup=markup)
    else:
        markup.add(finish_button)
        await hunter_bot.send_message(user_id, "Лимит в 5 фото достигнут. Нажмите 'Завершить', чтобы продолжить.", reply_markup=markup)

@hunter_bot.callback_query_handler(func=lambda call: call.data == 'add_more_photos')
async def handle_add_more_photos(call):
    await hunter_bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
    await hunter_bot.send_message(call.message.chat.id, "Присылайте следующее фото.")

@hunter_bot.callback_query_handler(func=lambda call: call.data == 'photos_done')
async def handle_offer_photos_done(call):
    user_id = call.message.chat.id
    state = get_user_state(user_id)
    if not state or not state['data'].get('photos'):
        await hunter_bot.answer_callback_query(call.id, "Пожалуйста, отправьте хотя бы одну фотографию.", show_alert=True)
        return
    set_user_state(user_id, 'offer_contact', state['data'])
    await hunter_bot.edit_message_text("Отлично! Фотографии добавлены.", user_id, call.message.message_id)
    await hunter_bot.send_message(user_id, "Последний шаг: напишите ваш контактный телефон или юзернейм в Telegram для связи.")

@hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_contact')
async def handle_offer_contact_and_submit(message):
    user_id = message.chat.id
    state = get_user_state(user_id)
    if not state: return
    state['data']['contact'] = message.text
    state['data']['author_username'] = message.from_user.username
    state['data']['author_id'] = user_id
    submission_id = f"sub_{user_id}_{int(datetime.now().timestamp())}"
    submission_type = f"rent_offer_{state['data']['rent_type']}"
    await save_submission_to_db(submission_id, submission_type, state['data'], user_id)
    await hunter_bot.send_message(user_id, "Спасибо! Ваше объявление отправлено на модерацию. Оно появится в канале сразу после проверки.")
    clear_user_state(user_id)

@hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'request_description')
async def handle_request_description_and_submit(message):
    user_id = message.chat.id
    submission_id = f"sub_{user_id}_{int(datetime.now().timestamp())}"
    data = {'description': message.text, 'author_username': message.from_user.username, 'author_id': user_id}
    await save_submission_to_db(submission_id, 'rent_request', data, user_id)
    await hunter_bot.send_message(user_id, "Ваша заявка на поиск принята и отправлена на модерацию. После проверки она появится в канале.")
    clear_user_state(user_id)

# --- БОТ-МОДЕРАТОР ---
@moderator_bot.message_handler(commands=['stats'])
async def handle_stats_command(message):
    if str(message.chat.id) == str(ADMIN_ID):
        try:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM submissions")
                pending_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM listings")
                active_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM listings WHERE date(published_at) = date('now')")
                today_count = cursor.fetchone()[0]
            stat_text = (f"📊 <b>Статистика 'Женева'</b>\n\n"
                         f"🔵 Ожидают модерации: <b>{pending_count}</b>\n"
                         f"🟢 Активных объявлений: <b>{active_count}</b>\n"
                         f"🗓 Опубликовано сегодня: <b>{today_count}</b>")
            await moderator_bot.send_message(ADMIN_ID, stat_text)
        except Exception as e:
            await moderator_bot.send_message(ADMIN_ID, f"Ошибка при получении статистики: {e}")

@moderator_bot.message_handler(func=lambda message: True)
async def handle_address_and_publish(message):
    user_id = message.chat.id
    submission = None
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT submission_type, data FROM pending_publication WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        if row:
            submission = {'type': row[0], 'data': json.loads(row[1])}
            cursor.execute("DELETE FROM pending_publication WHERE user_id=?", (user_id,))
            conn.commit()
    if not submission: return
    logger.info(f"[ДИАГНОСТИКА] Шаг 1: Получен адрес от {user_id}. Начинаю процесс публикации.")
    submission['data']['address'] = message.text
    submission_id = f"list_{user_id}_{int(datetime.now().timestamp())}"
    submission['data']['id'] = submission_id
    rent_type = submission['data'].get('rent_type')
    rent_type_text = "На долгий срок" if rent_type == 'long_term' else "Посуточно"
    price_suffix = "₽/мес." if rent_type == 'long_term' else "₽/сутки"
    caption = (f"<b>🏠 {rent_type_text}</b>\n\n"
               f"{escape(submission['data'].get('description', ''))}\n\n"
               f"📍 <b>Адрес:</b> {escape(submission['data'].get('address', ''))}\n"
               f"💰 <b>Цена:</b> {submission['data'].get('price', '')} {price_suffix}\n"
               f"📞 <b>Контакт:</b> {escape(submission['data'].get('contact', ''))}")
    photos_ids = submission['data'].get('photos', [])
    msg = None
    try:
        logger.info(f"[ДИАГНОСТИКА] Шаг 2: Подготовлен текст. Фото для обработки: {len(photos_ids)} шт.")
        if not photos_ids:
            logger.info("[ДИАГНОСТИКА] Шаг 3: Фото нет. Публикую только текст...")
            msg = await moderator_bot.send_message(CHANNEL_ID, caption)
        elif len(photos_ids) == 1:
            file_id = photos_ids[0]
            logger.info(f"[ДИАГНОСТИКА] Шаг 3: Обрабатываю одно фото (file_id: {file_id})")
            file_info = await hunter_bot.get_file(file_id)
            file_content = await hunter_bot.download_file(file_info.file_path)
            logger.info(f"[ДИАГНОСТИКА] Шаг 4: Файл скачан. Отправляю фото в канал...")
            msg = await moderator_bot.send_photo(CHANNEL_ID, file_content, caption=caption)
        else:
            logger.info(f"[ДИАГНОСТИКА] Шаг 3: Обрабатываю группу из {len(photos_ids)} фото.")
            media = []
            for i, file_id in enumerate(photos_ids):
                logger.info(f"[ДИАГНОСТИКА] Шаг 3.{i+1}: Скачиваю фото {file_id}")
                file_info = await hunter_bot.get_file(file_id)
                file_content = await hunter_bot.download_file(file_info.file_path)
                media.append(telebot.types.InputMediaPhoto(file_content, caption=caption if i == 0 else '', parse_mode='HTML'))
            if media:
                logger.info("[ДИАГНОСТИКА] Шаг 4: Отправляю медиа-группу в канал...")
                msgs = await asyncio.to_thread(sync_bot.send_media_group, CHANNEL_ID, media)
                msg = msgs[0] if msgs else None
        if msg:
            logger.info(f"[ДИАГНОСТИКА] Шаг 5: Публикация в канале УСПЕШНА (message_id: {msg.message_id}). Сохраняю в базу данных...")
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO listings (submission_id, listing_type, data, message_id) VALUES (?, ?, ?, ?)",
                               (submission_id, submission.get('type'), json.dumps(submission.get('data')), msg.message_id))
                conn.commit()
            await moderator_bot.send_message(user_id, "Отлично, адрес получен! Ваше объявление опубликовано в канале и добавлено на карту.")
            logger.info(f"Объявление {submission_id} полностью обработано.")
        else:
            raise Exception("Не удалось отправить сообщение в канал (объект сообщения не был получен).")
    except Exception as e:
        logger.exception(f"[ДИАГНОСТИКА] КРИТИЧЕСКАЯ ОШИБКА на этапе публикации от {user_id}: {e}")
        await moderator_bot.send_message(user_id, "К сожалению, при публикации вашего объявления произошла техническая ошибка. Администратор уже уведомлен.")
    finally:
        clear_user_state(user_id)

# --- WEB-СЕРВЕР ---
async def get_stats(request):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM submissions")
            pending_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM listings")
            active_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM listings WHERE date(published_at) = date('now')")
            today_count = cursor.fetchone()[0]
        return web.json_response({'pending_count': pending_count, 'active_count': active_count, 'today_count': today_count})
    except Exception as e:
        logger.exception(f"Ошибка API /api/stats: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_submissions(request):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT submission_id, submission_type, data FROM submissions ORDER BY created_at DESC")
            rows = cursor.fetchall()
            submissions = {row[0]: {'type': row[1], 'data': json.loads(row[2])} for row in rows}
        return web.json_response(submissions)
    except Exception as e:
        logger.exception(f"Ошибка API /api/submissions: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_listings(request):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT submission_id, listing_type, data FROM listings WHERE listing_type LIKE 'rent_offer_%'")
            rows = cursor.fetchall()
            listings = {row[0]: {'type': row[1], 'data': json.loads(row[2])} for row in rows}
        return web.json_response(listings)
    except Exception as e:
        logger.exception(f"Ошибка API /api/listings: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def get_image(request):
    file_id = request.match_info.get('file_id')
    if not file_id: return web.Response(status=404)
    try:
        file_info = await hunter_bot.get_file(file_id)
        file_content = await hunter_bot.download_file(file_info.file_path)
        return web.Response(body=file_content, content_type='image/jpeg')
    except Exception as e:
        logger.error(f"Ошибка при получении фото {file_id}: {e}")
        return web.Response(status=500)

async def approve_submission(request):
    data = await request.json()
    submission_id = data.get('id')
    logger.info(f"Получена команда ОДОБРИТЬ для ID: {submission_id}")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT submission_type, data FROM submissions WHERE submission_id=?", (submission_id,))
            row = cursor.fetchone()
            if not row:
                logger.warning(f"Заявка {submission_id} НЕ НАЙДЕНА в submissions.")
                return web.json_response({'status': 'error', 'message': 'Submission not found'}, status=404)
            submission_type, submission_data_json = row
            submission_data = json.loads(submission_data_json)
            user_id = submission_data.get('author_id')
            cursor.execute("DELETE FROM submissions WHERE submission_id=?", (submission_id,))
            if submission_type.startswith('rent_offer'):
                cursor.execute("INSERT OR REPLACE INTO pending_publication (user_id, submission_type, data) VALUES (?, ?, ?)",
                               (user_id, submission_type, submission_data_json))
                await moderator_bot.send_message(user_id, "🎉 Ваше объявление одобрено! Остался последний шаг: пожалуйста, пришлите точный адрес объекта (Город, Улица, Дом), чтобы мы могли добавить его на карту.")
            elif submission_type == 'rent_request':
                text = f"<b>🔍 Ищу жильё</b>\n\n{escape(submission_data.get('description'))}\n\n" \
                       f"<b>👤 Автор:</b> @{escape(submission_data.get('author_username') or 'скрыт')}"
                msg = await moderator_bot.send_message(CHANNEL_ID, text)
                cursor.execute("INSERT INTO listings (submission_id, listing_type, data, message_id) VALUES (?, ?, ?, ?)",
                               (submission_id, submission_type, submission_data_json, msg.message_id))
                await moderator_bot.send_message(user_id, "Ваша заявка на поиск одобрена и опубликована в канале!")
            conn.commit()
        logger.info(f"Заявка {submission_id} успешно одобрена.")
        return web.json_response({'status': 'ok'})
    except Exception as e:
        logger.exception(f"КРИТИЧЕСКАЯ ОШИБКА при ОДОБРЕНИИ заявки {submission_id}: {e}")
        return web.json_response({'status': 'error', 'message': 'Internal Server Error'}, status=500)

async def reject_submission(request):
    data = await request.json()
    submission_id = data.get('id')
    reason = data.get('reason', 'Причина не указана.')
    logger.info(f"Получена команда ОТКЛОНИТЬ для ID: {submission_id} с причиной: {reason}")
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM submissions WHERE submission_id=?", (submission_id,))
            row = cursor.fetchone()
            if not row:
                return web.json_response({'status': 'error', 'message': 'Submission not found'}, status=404)
            user_id = json.loads(row[0]).get('author_id')
            cursor.execute("DELETE FROM submissions WHERE submission_id=?", (submission_id,))
            conn.commit()
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

async def serve_admin_panel(request):
    return web.FileResponse('./admin_panel.html')

async def serve_public_map(request):
    return web.FileResponse('./public_map.html')

async def graceful_shutdown(app_runner, tasks):
    logger.info("Начинаю корректное завершение работы...")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if app_runner:
        await app_runner.cleanup()
    logger.info("Сервер и боты остановлены.")

async def main():
    init_db()
    app = web.Application()
    app.router.add_get('/api/stats', get_stats)
    app.router.add_get('/api/submissions', get_submissions)
    app.router.add_get('/api/listings', get_listings)
    app.router.add_get('/api/image/{file_id}', get_image)
    app.router.add_post('/api/approve', approve_submission)
    app.router.add_post('/api/reject', reject_submission)
    app.router.add_get('/admin', serve_admin_panel)
    app.router.add_get('/', serve_public_map)
    app.router.add_get('/map', serve_public_map)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    logger.info(f"Веб-сервер 'Женева' запущен на http://0.0.0.0:8080")
    
    logger.info("Запуск ботов...")
    polling_tasks = [
        asyncio.create_task(hunter_bot.polling(non_stop=True, request_timeout=90)),
        asyncio.create_task(moderator_bot.polling(non_stop=True, request_timeout=90))
    ]
    
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        if not stop_event.is_set():
            logger.info("Получен сигнал остановки, начинаю завершение...")
            stop_event.set()
            asyncio.create_task(graceful_shutdown(runner, polling_tasks))

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await asyncio.gather(*polling_tasks)
    except asyncio.CancelledError:
        logger.info("Задачи опроса ботов были отменены.")
        
if __name__ == '__main__':
    if not all([MODERATOR_BOT_TOKEN, HUNTER_BOT_TOKEN, CHANNEL_ID, ADMIN_ID]):
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Проверьте ваш .env файл.")
        exit(1)
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Сервер остановлен вручную.")
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка в главном цикле: {e}")

