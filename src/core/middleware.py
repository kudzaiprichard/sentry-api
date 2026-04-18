import time
import uuid
import logging
from fastapi import FastAPI
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.middleware.cors import CORSMiddleware
from src.configs import server, extension

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware:
    """
    Raw ASGI middleware for request logging and X-Request-ID injection.

    Stays raw ASGI on purpose — BaseHTTPMiddleware buffers response bodies
    and breaks SSE streaming. Every response gets an X-Request-ID header:
    the inbound value is echoed if present, otherwise a fresh UUID4 is generated.
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

        inbound_id = _extract_request_id(scope)
        request_id = inbound_id or str(uuid.uuid4())

        # Expose the id to downstream handlers via scope state.
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        status_code = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode("latin-1")))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)

        elapsed = round(time.perf_counter() - start, 4)
        logger.info(
            f"{method} {path} — {status_code} ({elapsed}s) [rid={request_id}]"
        )


def _extract_request_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"x-request-id":
            try:
                candidate = value.decode("latin-1").strip()
            except UnicodeDecodeError:
                return None
            if candidate:
                return candidate[:128]
    return None


def register_middleware(app: FastAPI) -> None:
    # Order matters: first added = outermost middleware
    # CORS must be outermost to handle preflight requests
    _add_cors(app)
    # Logging as raw ASGI middleware — does NOT break SSE
    app.add_middleware(RequestLoggingMiddleware)


def _add_cors(app: FastAPI) -> None:
    combined_origins = list(server.cors.origins) + list(extension.cors_origins)
    seen: set[str] = set()
    ordered: list[str] = []
    for origin in combined_origins:
        if origin and origin not in seen:
            seen.add(origin)
            ordered.append(origin)

    # Browsers reject `Access-Control-Allow-Origin: *` when credentials are
    # enabled, so refuse to boot with that combination rather than serving
    # requests that every browser will reject.
    if server.cors.allow_credentials and "*" in ordered:
        raise RuntimeError(
            "CORS misconfiguration: allow_credentials=True is incompatible "
            "with origin '*'. Replace '*' with specific origins or set "
            "CORS_ALLOW_CREDENTIALS=false."
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ordered,
        allow_origin_regex=server.cors.origin_regex,
        allow_credentials=server.cors.allow_credentials,
        allow_methods=server.cors.allow_methods,
        allow_headers=server.cors.allow_headers,
        expose_headers=["X-Request-ID"],
    )
