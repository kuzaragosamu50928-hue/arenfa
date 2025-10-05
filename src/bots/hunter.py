"""
Handlers for the "Hunter" bot.

This module contains all the Telegram bot handlers for the user-facing
workflow, which includes submitting new rental offers and requests.
It uses a state machine pattern to guide the user through the process.
"""
from datetime import datetime
from telebot.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from .utils import hunter_bot, moderator_bot
from src import database as db
from src.config import SUBMISSION_COOLDOWN, ADMIN_ID, DOMAIN_NAME, logger

async def is_on_cooldown(user_id: int) -> bool:
    """Checks if a user is in the submission cooldown period."""
    last_submission_time = await db.get_last_submission_time(user_id)
    if last_submission_time and (datetime.now() - last_submission_time).total_seconds() < SUBMISSION_COOLDOWN:
        remaining = int(SUBMISSION_COOLDOWN - (datetime.now() - last_submission_time).total_seconds())
        await hunter_bot.send_message(
            user_id,
            f"⏳ Вы слишком часто подаете объявления. "
            f"Пожалуйста, подождите еще примерно {remaining // 60} мин."
        )
        return True
    return False

async def notify_admin_of_new_submission():
    """Sends a notification to the admin about a new submission."""
    if not ADMIN_ID:
        return
    try:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("Перейти в админ-панель", url=f"http://{DOMAIN_NAME}/admin"))
        await moderator_bot.send_message(ADMIN_ID, "🛎️ Новая заявка на модерацию!", reply_markup=markup)
    except Exception as e:
        logger.error(f"Failed to send notification to admin {ADMIN_ID}: {e}")

async def finalize_submission(user_id: int, state: dict, submission_type: str):
    """Saves the submission to the DB, notifies admin, and cleans up state."""
    submission_id = f"sub_{user_id}_{int(datetime.now().timestamp())}"
    await db.save_submission_to_db(submission_id, submission_type, state['data'], user_id)
    await notify_admin_of_new_submission()
    await hunter_bot.send_message(user_id, "Спасибо! Ваше объявление отправлено на модерацию. Оно появится в канале сразу после проверки.")
    await db.clear_user_state(user_id)

def register_hunter_handlers():
    """Registers all handlers for the Hunter bot."""

    @hunter_bot.message_handler(commands=['start'])
    async def handle_start(message: Message):
        user_id = message.chat.id
        if await is_on_cooldown(user_id):
            return

        await db.clear_user_state(user_id)
        await db.set_user_state(user_id, 'start', {})

        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(InlineKeyboardButton('🏠 Сдать жильё', callback_data='action_offer'))
        markup.add(InlineKeyboardButton('🔍 Ищу жильё', callback_data='action_request'))
        await hunter_bot.send_message(
            user_id,
            "Здравствуйте! Я помогу вам сдать или найти жильё в Мелитополе.\n\n"
            "Что вы хотите сделать?",
            reply_markup=markup
        )

    @hunter_bot.callback_query_handler(func=lambda call: call.data.startswith('action_'))
    async def handle_action_choice(call: CallbackQuery):
        user_id = call.message.chat.id
        action = call.data.split('_')[1]

        if action == 'offer':
            await db.set_user_state(user_id, 'offer_type', {'type': 'rent_offer'})
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton('🗓 На долгий срок', callback_data='type_long_term'),
                InlineKeyboardButton('☀️ Посуточно', callback_data='type_daily')
            )
            await hunter_bot.edit_message_text(
                "Отлично! Вы хотите сдать жильё на долгий срок или посуточно?",
                user_id, call.message.message_id, reply_markup=markup
            )
        elif action == 'request':
            await db.set_user_state(user_id, 'request_description', {'type': 'rent_request'})
            await hunter_bot.edit_message_text(
                "Понимаю. Опишите в одном сообщении, какое жильё вы ищете "
                "(район, кол-во комнат, бюджет и т.д.). Эту заявку увидят собственники.",
                user_id, call.message.message_id
            )

    @hunter_bot.callback_query_handler(func=lambda call: call.data.startswith('type_'))
    async def handle_offer_type(call: CallbackQuery):
        user_id = call.message.chat.id
        rent_type = call.data.replace('type_', '')
        state = await db.get_user_state(user_id)
        if not state: return

        state['data']['rent_type'] = rent_type
        await db.set_user_state(user_id, 'offer_description', state['data'])
        await hunter_bot.edit_message_text(
            "Теперь, пожалуйста, напишите подробное описание вашего жилья: "
            "кол-во комнат, адрес, состояние, мебель, техника и т.д. "
            "Вся информация в одном сообщении.",
            user_id, call.message.message_id
        )

    @hunter_bot.callback_query_handler(func=lambda call: call.data == 'add_more_photos')
    async def handle_add_more_photos(call: CallbackQuery):
        await hunter_bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
        await hunter_bot.send_message(call.message.chat.id, "Присылайте следующее фото.")

    @hunter_bot.callback_query_handler(func=lambda call: call.data == 'photos_done')
    async def handle_offer_photos_done(call: CallbackQuery):
        user_id = call.message.chat.id
        state = await db.get_user_state(user_id)
        if not state or not state['data'].get('photos'):
            await hunter_bot.answer_callback_query(call.id, "Пожалуйста, отправьте хотя бы одну фотографию.", show_alert=True)
            return

        await db.set_user_state(user_id, 'offer_contact', state['data'])
        await hunter_bot.edit_message_text("Отлично! Фотографии добавлены.", user_id, call.message.message_id)
        await hunter_bot.send_message(user_id, "Последний шаг: напишите ваш контактный телефон или юзернейм в Telegram для связи.")

    # --- State-based Message Handlers ---

    @hunter_bot.message_handler(content_types=['text', 'photo'])
    async def handle_stateful_messages(message: Message):
        """
        A single handler that routes messages based on the user's current state.
        """
        user_id = message.chat.id
        state = await db.get_user_state(user_id)

        if not state:
            await hunter_bot.send_message(user_id, "Чтобы начать, пожалуйста, используйте команду /start.")
            return

        current_step = state.get('step')

        # --- Offer Workflow ---
        if current_step == 'offer_description':
            state['data']['description'] = message.text
            rent_type = state['data'].get('rent_type')
            price_question = "Укажите цену в рублях за месяц." if rent_type == 'long_term' else "Укажите цену в рублях за сутки."
            await db.set_user_state(user_id, 'offer_price', state['data'])
            await hunter_bot.send_message(user_id, f"Отлично. {price_question} Просто напишите число.")

        elif current_step == 'offer_price':
            if message.text and message.text.isdigit():
                state['data']['price'] = int(message.text)
                state['data']['photos'] = []
                await db.set_user_state(user_id, 'offer_photos', state['data'])
                await hunter_bot.send_message(user_id, "Понял. Теперь отправьте, пожалуйста, ваше лучшее фото. Позже можно будет добавить еще.")
            else:
                await hunter_bot.send_message(user_id, "Пожалуйста, введите цену цифрами, без других символов.")

        elif current_step == 'offer_photos':
            if message.content_type == 'photo':
                state['data']['photos'].append(message.photo[-1].file_id)
                await db.set_user_state(user_id, 'offer_photos', state['data'])

                markup = InlineKeyboardMarkup(row_width=2)
                finish_button = InlineKeyboardButton("✅ Завершить", callback_data="photos_done")

                if len(state['data']['photos']) < 5:
                    add_more_button = InlineKeyboardButton("➕ Добавить еще", callback_data="add_more_photos")
                    markup.add(add_more_button, finish_button)
                    await hunter_bot.send_message(user_id, f"Фото {len(state['data']['photos'])}/5 добавлено. Хотите добавить еще или завершить?", reply_markup=markup)
                else:
                    markup.add(finish_button)
                    await hunter_bot.send_message(user_id, "Лимит в 5 фото достигнут. Нажмите 'Завершить', чтобы продолжить.", reply_markup=markup)
            else:
                await hunter_bot.send_message(user_id, "Пожалуйста, отправьте фото.")

        elif current_step == 'offer_contact':
            state['data']['contact'] = message.text
            state['data']['author_username'] = message.from_user.username
            state['data']['author_id'] = user_id
            submission_type = f"rent_offer_{state['data']['rent_type']}"
            await finalize_submission(user_id, state, submission_type)

        # --- Request Workflow ---
        elif current_step == 'request_description':
            state['data']['description'] = message.text
            state['data']['author_username'] = message.from_user.username
            state['data']['author_id'] = user_id
            await finalize_submission(user_id, state, 'rent_request')

    logger.info("Handlers for the Hunter Bot have been registered.")