"""Verify a Google access token against Google's userinfo + tokeninfo endpoints.

Contract rules (VERIFY §12, STANDARD §9):
- 10 second timeout — keeps the call inside the extension's 30 s client budget.
- Non-200 or transport failure → raise ServiceUnavailableException (503).
- Never log the access token or any PII beyond ``sub`` and ``email`` (domain).
- When ``extension.google_oauth.client_id`` is configured, verify the token's
  audience matches it by calling tokeninfo. Mismatch must surface as 401
  ``GOOGLE_AUTH_FAILED`` — raised by the caller, so this module signals it
  via ``InvalidAudience``.

``verify_access_token`` returns the parsed userinfo dict on success. Callers
compare ``sub`` / ``email`` against the request body and apply the allow-list
themselves.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from src.configs import extension
from src.shared.exceptions import ServiceUnavailableException
from src.shared.responses import ErrorDetail


logger = logging.getLogger(__name__)

USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
TOKENINFO_URL = "https://www.googleapis.com/oauth2/v3/tokeninfo"
TIMEOUT_SECONDS = 10.0


class InvalidAudience(Exception):
    """Raised when tokeninfo returns an audience that does not match config.

    The caller converts this to a 401 ``GOOGLE_AUTH_FAILED`` with the required
    title — keeping envelope construction out of this module.
    """


def _unavailable(detail: str) -> ServiceUnavailableException:
    return ServiceUnavailableException(
        message="Google verification is temporarily unavailable",
        error_detail=ErrorDetail(
            title="Google Unavailable",
            code="SERVICE_UNAVAILABLE",
            status=503,
            details=[detail],
        ),
    )


async def _fetch_userinfo(client: httpx.AsyncClient, access_token: str) -> dict[str, Any]:
    try:
        response = await client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    except httpx.HTTPError as exc:
        logger.warning("Google userinfo request failed: %s", type(exc).__name__)
        raise _unavailable("Network error contacting Google")

    if response.status_code != 200:
        logger.info(
            "Google userinfo returned non-200: status=%s", response.status_code
        )
        raise _unavailable(f"Google returned status {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        raise _unavailable("Google response was not valid JSON")

    if not isinstance(payload, dict):
        raise _unavailable("Google response was not a JSON object")

    return payload


async def _verify_audience(client: httpx.AsyncClient, access_token: str) -> None:
    expected = (extension.google_oauth.client_id or "").strip()
    if not expected:
        return  # No client_id configured → audience check is opt-in.

    try:
        response = await client.get(
            TOKENINFO_URL, params={"access_token": access_token}
        )
    except httpx.HTTPError as exc:
        logger.warning("Google tokeninfo request failed: %s", type(exc).__name__)
        raise _unavailable("Network error contacting Google")

    if response.status_code != 200:
        logger.info(
            "Google tokeninfo returned non-200: status=%s", response.status_code
        )
        raise _unavailable(f"Google returned status {response.status_code}")

    try:
        payload = response.json()
    except ValueError:
        raise _unavailable("Google tokeninfo response was not valid JSON")

    if not isinstance(payload, dict):
        raise _unavailable("Google tokeninfo response was not a JSON object")

    # tokeninfo v3 returns `aud` and `azp`. `azp` (authorized party) is what
    # matches the extension's OAuth client id; `aud` can be the Google service.
    claimed = payload.get("azp") or payload.get("aud")
    if claimed != expected:
        raise InvalidAudience()


async def verify_access_token(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        await _verify_audience(client, access_token)
        return await _fetch_userinfo(client, access_token)
