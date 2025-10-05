"""
Middleware for the aiohttp web application.

This module provides middleware functions for centralized request logging
and robust error handling.
"""
import logging
from typing import Awaitable, Callable
from aiohttp import web
from aiohttp.web_request import Request
from aiohttp.web_response import Response

logger = logging.getLogger(__name__)

@web.middleware
async def logging_middleware(request: Request, handler: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Logs information about each incoming request.
    """
    logger.info(
        f"Request: {request.method} {request.path} from {request.remote}"
    )
    return await handler(request)

@web.middleware
async def error_handling_middleware(request: Request, handler: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Catches exceptions and returns a standardized JSON error response.

    This prevents stack traces from being leaked to the client and ensures
    a consistent error format for the API.
    """
    try:
        return await handler(request)
    except web.HTTPException as ex:
        # HTTP exceptions are already proper responses, so re-raise them
        raise ex
    except Exception as e:
        # For all other exceptions, log the full error and return a generic 500 response
        logger.exception(f"Unhandled exception for request {request.method} {request.path}: {e}")
        return web.json_response(
            {'status': 'error', 'message': 'Internal Server Error'},
            status=500
        )