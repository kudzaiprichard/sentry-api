"""slowapi limiter + key functions for the extension surface.

The limiter is a module-level singleton: it must be attached to
``app.state.limiter`` at startup and the ``SlowAPIMiddleware`` must be
registered before any decorated route runs. Each extension endpoint pulls its
rate string from ``server.rate_limit.*`` so ops can tune without redeploying.

``install_token_key`` hashes the bearer token with SHA-256 so the 60/min cap on
``/emails/analyze`` survives across IPs for the same install, matching the hash
stored in ``extension_tokens``. If the header is missing we fall back to the
remote address — covers the 401 path cleanly without bypassing the limiter.
"""

from __future__ import annotations

import hashlib

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


limiter = Limiter(key_func=get_remote_address)


def install_token_key(request: Request) -> str:
    """Rate-limit key for /emails/analyze — SHA-256 of the bearer token."""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token:
            return "install:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
    return "ip:" + get_remote_address(request)
