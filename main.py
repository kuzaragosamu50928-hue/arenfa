import asyncio
import signal
import os
from aiohttp import web
from typing import List

# Важно: Сначала импортируем и валидируем конфигурацию
from src.config import logger, DB_PATH, validate_config
validate_config()

from src.database import init_db
from src.bots.utils import hunter_bot, moderator_bot
from src.bots.hunter import register_hunter_handlers
from src.bots.moderator import register_moderator_handlers
from src.web.routes import setup_routes
from src.web.middleware import logging_middleware, error_handling_middleware


async def start_bots(app: web.Application):
    """Регистрирует хендлеры и запускает long-polling для ботов."""
    logger.info("Регистрация обработчиков ботов...")
    register_hunter_handlers()
    register_moderator_handlers()

    logger.info("Запуск ботов в режиме polling...")
    # Store polling tasks to be able to cancel them later
    app['bot_tasks'] = [
        asyncio.create_task(hunter_bot.polling(non_stop=True, request_timeout=90)),
        asyncio.create_task(moderator_bot.polling(non_stop=True, request_timeout=90))
    ]

async def stop_bots(app: web.Application):
    """Останавливает long-polling для ботов."""
    logger.info("Остановка задач опроса ботов...")
    if 'bot_tasks' in app:
        for task in app['bot_tasks']:
            task.cancel()
        await asyncio.gather(*app['bot_tasks'], return_exceptions=True)
    logger.info("Задачи опроса ботов остановлены.")


async def main():
    """Главная функция для настройки и запуска приложения."""
    # Создаем директорию для БД здесь, т.к. это синхронная операция
    db_dir = os.path.dirname(DB_PATH)
    os.makedirs(db_dir, exist_ok=True)

    # Инициализируем БД
    await init_db()

    # Создаем веб-приложение с мидлварями
    app = web.Application(middlewares=[logging_middleware, error_handling_middleware])

    # Настраиваем обработчики сигналов для корректного завершения
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(graceful_shutdown(app)))

    # Привязываем запуск и остановку ботов к жизненному циклу веб-приложения
    app.on_startup.append(start_bots)
    app.on_cleanup.append(stop_bots)

    # Настраиваем и запускаем веб-сервер
    setup_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)

    logger.info("Веб-сервер 'Женева' запущен на http://0.0.0.0:8080")
    await site.start()

    # Поддерживаем работу сервера
    await asyncio.Event().wait()


async def graceful_shutdown(app: web.Application):
    """Координация корректного завершения работы."""
    logger.info("Получен сигнал остановки, начинаю корректное завершение...")
    # Остановка ботов уже будет вызвана через on_cleanup
    # Главный цикл завершится, когда веб-сервер остановится
    # Достаточно остановить основной Event, чтобы главный 'main' цикл завершился
    # и позволил выполниться cleanup операциям.
    # Найдем и отмним задачу, которая ждет Event
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        if "wait" in str(task): # Не очень надежный способ, но для этого случая сработает
             task.cancel()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Приложение остановлено.")
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка в главном цикле: {e}")