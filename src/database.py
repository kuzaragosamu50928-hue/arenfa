import aiosqlite
import json
import logging
from datetime import datetime
from .config import DB_PATH, logger

# --- Инициализация базы данных ---
async def init_db():
    """Асинхронно инициализирует базу данных и создает таблицы, если они не существуют."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS user_sessions (
                                user_id INTEGER PRIMARY KEY,
                                step TEXT NOT NULL,
                                data TEXT NOT NULL,
                                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS submissions (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                submission_id TEXT UNIQUE NOT NULL,
                                submission_type TEXT NOT NULL,
                                data TEXT NOT NULL,
                                user_id INTEGER,
                                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                            )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS pending_publication (
                                user_id INTEGER PRIMARY KEY,
                                submission_type TEXT NOT NULL,
                                data TEXT NOT NULL
                            )''')
        await db.execute('''CREATE TABLE IF NOT EXISTS listings (
                                id INTEGER PRIMARY KEY AUTOINCREMENT,
                                submission_id TEXT UNIQUE NOT NULL,
                                listing_type TEXT NOT NULL,
                                data TEXT NOT NULL,
                                message_id INTEGER,
                                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                            )''')
        await db.commit()
        logger.info("База данных 'Женева' успешно инициализирована.")

# --- Управление состоянием пользователя ---
async def get_user_state(user_id):
    """Асинхронно получает состояние пользователя (шаг и данные)."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT step, data FROM user_sessions WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {'step': row[0], 'data': json.loads(row[1])}
    except Exception as e:
        logger.error(f"Ошибка при получении состояния пользователя {user_id}: {e}")
    return None

async def set_user_state(user_id, step, data):
    """Асинхронно сохраняет или обновляет состояние пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO user_sessions (user_id, step, data, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                         (user_id, step, json.dumps(data, ensure_ascii=False)))
        await db.commit()

async def clear_user_state(user_id):
    """Асинхронно удаляет состояние пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        await db.commit()

# --- Управление заявками и объявлениями ---
async def save_submission_to_db(submission_id, submission_type, data, user_id):
    """Асинхронно сохраняет новую заявку в базу данных."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO submissions (submission_id, submission_type, data, user_id, created_at) VALUES (?, ?, ?, ?, ?)",
                         (submission_id, submission_type, json.dumps(data, ensure_ascii=False), user_id, datetime.now()))
        await db.commit()

async def get_last_submission_time(user_id):
    """Асинхронно получает время последней заявки пользователя."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT created_at FROM submissions WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row and row[0]:
                try:
                    return datetime.fromisoformat(row[0])
                except (ValueError, TypeError):
                    logger.warning(f"Не удалось распознать формат даты: {row[0]}")
    return None

async def add_listing(submission_id, listing_type, data, message_id):
    """Асинхронно добавляет опубликованное объявление в базу."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO listings (submission_id, listing_type, data, message_id) VALUES (?, ?, ?, ?)",
                         (submission_id, listing_type, json.dumps(data, ensure_ascii=False), message_id))
        await db.commit()