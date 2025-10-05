import asyncio
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from .utils import hunter_bot
from src.database import (
    get_user_state,
    set_user_state,
    clear_user_state,
    save_submission_to_db,
    get_last_submission_time
)
from src.config import SUBMISSION_COOLDOWN, ADMIN_ID, DOMAIN_NAME, logger
from src.bots.utils import moderator_bot

# --- ЛОГИКА БОТА-ОХОТНИКА ---

def register_hunter_handlers():
    """Регистрирует все обработчики для бота-охотника."""

    @hunter_bot.message_handler(commands=['start'])
    async def handle_start(message):
        user_id = message.chat.id

        last_submission_time = await get_last_submission_time(user_id)
        if last_submission_time and (datetime.now() - last_submission_time).total_seconds() < SUBMISSION_COOLDOWN:
            await hunter_bot.send_message(user_id, "⏳ Вы слишком часто подаете объявления. Пожалуйста, подождите еще несколько минут.")
            return

        await clear_user_state(user_id)
        await set_user_state(user_id, 'start', {})
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton('🏠 Сдать жильё', callback_data='action_offer'))
        markup.add(InlineKeyboardButton('🔍 Ищу жильё', callback_data='action_request'))
        await hunter_bot.send_message(user_id, "Здравствуйте! Я помогу вам сдать или найти жильё в Мелитополе.\n\nЧто вы хотите сделать?", reply_markup=markup)

    @hunter_bot.callback_query_handler(func=lambda call: call.data.startswith('action_'))
    async def handle_action_choice(call):
        user_id = call.message.chat.id
        action = call.data.split('_')[1]

        if action == 'offer':
            await set_user_state(user_id, 'offer_type', {'type': 'rent_offer'})
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(InlineKeyboardButton('🗓 На долгий срок', callback_data='type_long_term'),
                       InlineKeyboardButton('☀️ Посуточно', callback_data='type_daily'))
            await hunter_bot.edit_message_text("Отлично! Вы хотите сдать жильё на долгий срок или посуточно?", user_id, call.message.message_id, reply_markup=markup)
        elif action == 'request':
            await set_user_state(user_id, 'request_description', {'type': 'rent_request'})
            await hunter_bot.edit_message_text("Понимаю. Опишите в одном сообщении, какое жильё вы ищете (район, кол-во комнат, бюджет и т.д.). Эту заявку увидят собственники.", user_id, call.message.message_id)

    @hunter_bot.callback_query_handler(func=lambda call: call.data.startswith('type_'))
    async def handle_offer_type(call):
        user_id = call.message.chat.id
        rent_type = call.data.replace('type_', '')
        state = await get_user_state(user_id)
        if not state: return
        state['data']['rent_type'] = rent_type
        await set_user_state(user_id, 'offer_description', state['data'])
        await hunter_bot.edit_message_text("Теперь, пожалуйста, напишите подробное описание вашего жилья: кол-во комнат, адрес, состояние, мебель, техника и т.д. Вся информация в одном сообщении.", user_id, call.message.message_id)

    async def process_text_input(message, current_step_name, next_step, prompt):
        user_id = message.chat.id
        state = await get_user_state(user_id)
        if not (state and state['step'] == current_step_name): return
        state['data'][current_step_name.replace('offer_', '')] = message.text
        await set_user_state(user_id, next_step, state['data'])
        await hunter_bot.send_message(user_id, prompt)

    @hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_description')
    async def handle_offer_description(message):
        state = await get_user_state(message.chat.id)
        if not state: return
        rent_type = state['data'].get('rent_type')
        price_question = "Укажите цену в рублях за месяц." if rent_type == 'long_term' else "Укажите цену в рублях за сутки."
        await process_text_input(message, 'offer_description', 'offer_price', f"Отлично. {price_question} Просто напишите число.")

    @hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_price')
    async def handle_offer_price(message):
        if message.text.isdigit():
            state = await get_user_state(message.chat.id)
            if not state: return
            state['data']['price'] = int(message.text)
            state['data']['photos'] = []
            await set_user_state(message.chat.id, 'offer_photos', state['data'])
            await hunter_bot.send_message(message.chat.id, "Понял. Теперь отправьте, пожалуйста, ваше лучшее фото. Позже можно будет добавить еще.")
        else:
            await hunter_bot.send_message(message.chat.id, "Пожалуйста, введите цену цифрами, без других символов.")

    @hunter_bot.message_handler(content_types=['photo'], func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_photos')
    async def handle_offer_photos(message):
        user_id = message.chat.id
        state = await get_user_state(user_id)
        if not state: return

        state['data']['photos'].append(message.photo[-1].file_id)
        await set_user_state(user_id, 'offer_photos', state['data'])

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
        state = await get_user_state(user_id)
        if not state or not state['data'].get('photos'):
            await hunter_bot.answer_callback_query(call.id, "Пожалуйста, отправьте хотя бы одну фотографию.", show_alert=True)
            return
        await set_user_state(user_id, 'offer_contact', state['data'])
        await hunter_bot.edit_message_text("Отлично! Фотографии добавлены.", user_id, call.message.message_id)
        await hunter_bot.send_message(user_id, "Последний шаг: напишите ваш контактный телефон или юзернейм в Telegram для связи.")

    async def finalize_submission(user_id, state, submission_type):
        submission_id = f"sub_{user_id}_{int(datetime.now().timestamp())}"
        await save_submission_to_db(submission_id, submission_type, state['data'], user_id)

        # Уведомление админа
        if ADMIN_ID:
            try:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("Перейти в админ-панель", url=f"http://{DOMAIN_NAME}/admin"))
                await moderator_bot.send_message(ADMIN_ID, "🛎️ Новая заявка на модерацию!", reply_markup=markup)
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {ADMIN_ID}: {e}")

        await hunter_bot.send_message(user_id, "Спасибо! Ваше объявление отправлено на модерацию. Оно появится в канале сразу после проверки.")
        await clear_user_state(user_id)

    @hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'offer_contact')
    async def handle_offer_contact_and_submit(message):
        user_id = message.chat.id
        state = await get_user_state(user_id)
        if not state: return
        state['data']['contact'] = message.text
        state['data']['author_username'] = message.from_user.username
        state['data']['author_id'] = user_id
        submission_type = f"rent_offer_{state['data']['rent_type']}"
        await finalize_submission(user_id, state, submission_type)

    @hunter_bot.message_handler(func=lambda m: get_user_state(m.chat.id) and get_user_state(m.chat.id).get('step') == 'request_description')
    async def handle_request_description_and_submit(message):
        user_id = message.chat.id
        state = await get_user_state(user_id)
        if not state: return
        state['data']['description'] = message.text
        state['data']['author_username'] = message.from_user.username
        state['data']['author_id'] = user_id
        await finalize_submission(user_id, state, 'rent_request')

    # Этот хандлер нужно будет переписать, чтобы он не конфликтовал с другими.
    # Пока оставляем его как есть, но с `get_user_state` проверкой
    @hunter_bot.message_handler(func=lambda m: not get_user_state(m.chat.id))
    async def handle_unsolicited_messages(message):
        await hunter_bot.send_message(message.chat.id, "Чтобы начать, пожалуйста, используйте команду /start.")

    logger.info("Обработчики бота-охотника зарегистрированы.")