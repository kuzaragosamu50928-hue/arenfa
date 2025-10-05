import asyncio
import signal
import os
from aiohttp import web

# Важно: Сначала импортируем и валидируем конфигурацию
from src.config import logger, validate_config
validate_config()

from src.database import init_db
from src.bots.utils import hunter_bot, moderator_bot
from src.bots.hunter import register_hunter_handlers
from src.bots.moderator import register_moderator_handlers
from src.web.routes import setup_routes

async def start_bots():
    """Регистрирует хендлеры и запускает long-polling для ботов."""
    logger.info("Регистрация обработчиков ботов...")
    register_hunter_handlers()
    register_moderator_handlers()

    logger.info("Запуск ботов в режиме polling...")
    await asyncio.gather(
        hunter_bot.polling(non_stop=True, request_timeout=90),
        moderator_bot.polling(non_stop=True, request_timeout=90)
    )

async def start_webapp():
    """Создает и запускает веб-приложение aiohttp."""
    app = web.Application()
    setup_routes(app)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    logger.info("Веб-сервер 'Женева' запущен на http://0.0.0.0:8080")
    await site.start()
    # Эта сопрограмма будет работать вечно, пока не будет отменена
    await asyncio.Event().wait()
    # Корректное завершение работы
    logger.info("Остановка веб-сервера...")
    await runner.cleanup()

async def main():
    """Главная функция для запуска приложения."""
    # Убедимся, что директория для БД существует
    os.makedirs(os.path.dirname('app_data/dummy'), exist_ok=True)
    await init_db()

    # Запускаем ботов и веб-сервер как фоновые задачи
    main_tasks = [
        asyncio.create_task(start_bots()),
        asyncio.create_task(start_webapp())
    ]

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def signal_handler():
        logger.info("Получен сигнал остановки, начинаю корректное завершение...")
        # Устанавливаем событие, чтобы главный цикл мог завершиться, если он его ждет
        stop_event.set()
        # Отменяем все основные задачи
        for task in main_tasks:
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        # Ожидаем завершения всех задач (они будут отменены по сигналу)
        await asyncio.gather(*main_tasks, return_exceptions=True)
    except asyncio.CancelledError:
        logger.info("Основные задачи были отменены. Приложение завершает работу.")
    finally:
        # Здесь можно добавить дополнительную логику очистки, если необходимо
        logger.info("Приложение успешно остановлено.")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Сервер остановлен вручную.")
    except Exception as e:
        logger.exception(f"Непредвиденная ошибка в главном цикле: {e}")