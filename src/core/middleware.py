import time
import logging
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.middleware.cors import CORSMiddleware
from src.configs import server

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """
    Raw ASGI middleware for request logging.
    Unlike BaseHTTPMiddleware / @app.middleware("http"),
    this does NOT buffer the response body — so SSE streaming works.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        method = scope.get("method", "?")
        path = scope.get("path", "?")

        status_code = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        elapsed = round(time.perf_counter() - start, 4)
        logger.info(f"{method} {path} — {status_code} ({elapsed}s)")


def register_middleware(app: FastAPI) -> None:
    # Order matters: first added = outermost middleware
    # CORS must be outermost to handle preflight requests
    _add_cors(app)
    # Logging as raw ASGI middleware — does NOT break SSE
    app.add_middleware(RequestLoggingMiddleware)


def _add_cors(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=server.cors.origins,
        allow_credentials=server.cors.allow_credentials,
        allow_methods=server.cors.allow_methods,
        allow_headers=server.cors.allow_headers,
    )
