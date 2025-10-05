from aiohttp import web
from . import handlers

def setup_routes(app: web.Application):
    """Настраивает все маршруты для веб-приложения."""

    # API маршруты
    app.router.add_get('/api/stats', handlers.get_stats)
    app.router.add_get('/api/submissions', handlers.get_submissions)
    app.router.add_get('/api/listings', handlers.get_listings)
    app.router.add_get('/api/image/{file_id}', handlers.get_image)
    app.router.add_post('/api/approve', handlers.approve_submission)
    app.router.add_post('/api/reject', handlers.reject_submission)

    # Маршруты для статических страниц
    app.router.add_get('/admin', handlers.serve_admin_panel)

    # Главная страница и карта (пока ведут на заглушку/админку)
    app.router.add_get('/', handlers.serve_public_map)
    app.router.add_get('/map', handlers.serve_public_map)

    # Добавим обработку статических файлов, если они понадобятся в будущем
    # app.router.add_static('/static/', path='path/to/static', name='static')