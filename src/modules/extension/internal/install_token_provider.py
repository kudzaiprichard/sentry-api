"""Opaque install tokens — mint / hash / verify / revoke.

Tokens are random strings issued to Chrome installs and stored only as their
SHA-256 hex hash in ``extension_tokens``. Nothing is persisted or logged in
cleartext. Mirror the dashboard's ``token_provider`` so lifespan and cleanup
follow the same shape.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.configs import security
from src.modules.extension.domain.models.extension_token import ExtensionToken
from src.modules.extension.domain.repositories.extension_token_repository import (
    ExtensionTokenRepository,
)


TOKEN_BYTES = 32  # → 256 bits, URL-safe base64 ≈ 43 chars


@dataclass(frozen=True)
class IssuedToken:
    token: str
    token_hash: str
    expires_at: datetime


def hash_token(token: str) -> str:
    """SHA-256 hex of the token — lookup key for extension_tokens.token_hash."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


async def issue_token(
    install_id: UUID, token_repo: ExtensionTokenRepository
) -> IssuedToken:
    token = _new_token()
    token_hash = hash_token(token)
    expires_at = datetime.now(timezone.utc) + timedelta(
        days=security.extension_token_expire_days
    )

    await token_repo.create(
        ExtensionToken(
            install_id=install_id,
            token_hash=token_hash,
            is_revoked=False,
            expires_at=expires_at,
        )
    )
    return IssuedToken(token=token, token_hash=token_hash, expires_at=expires_at)


async def rotate_token(
    *,
    install_id: UUID,
    current_token_hash: str,
    token_repo: ExtensionTokenRepository,
    reason: str = "rotated",
) -> IssuedToken:
    """Atomic revoke-current + issue-new used by /auth/extension/renew."""
    await token_repo.revoke_by_hash(current_token_hash, reason=reason)
    return await issue_token(install_id, token_repo)


def epoch_millis(dt: datetime) -> int:
    """Wire format for expiresAt — epoch milliseconds, UTC."""
    return int(dt.timestamp() * 1000)
