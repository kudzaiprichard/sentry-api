"""Business logic for the three extension auth endpoints.

Handles register/renew/logout. Kept separate from ``AuthService`` so the
dashboard JWT flow is never touched.

Logging — EXTENSION_IMPLEMENTATION_STANDARD §15:
- Never log the Google access token
- Never log the raw install bearer token
- On register INFO: install_id, email domain only, truncated google_sub, outcome
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.modules.extension.domain.models.enums import InstallStatus
from src.modules.extension.domain.models.extension_install import (
    ExtensionInstall,
)
from src.modules.extension.domain.repositories.extension_token_repository import (
    ExtensionTokenRepository,
)
from src.modules.extension.domain.repositories.install_repository import (
    InstallRepository,
)
from src.modules.extension.internal import (
    allow_list,
    google_verifier,
    install_token_provider,
)
from src.shared.exceptions import (
    AuthenticationException,
    AuthorizationException,
)
from src.shared.responses import ErrorDetail


logger = logging.getLogger(__name__)


def _truncate_sub(sub: str) -> str:
    return f"{sub[:6]}…" if len(sub) > 6 else sub


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[1] if "@" in email else "?"


def _google_auth_failed(detail: str) -> AuthenticationException:
    return AuthenticationException(
        message="Google sign-in could not be verified",
        error_detail=ErrorDetail(
            title="Google sign-in could not be verified",
            code="GOOGLE_AUTH_FAILED",
            status=401,
            details=[detail],
        ),
    )


def _not_whitelisted(detail: str) -> AuthorizationException:
    return AuthorizationException(
        message="Your account is not authorised for AURA",
        error_detail=ErrorDetail(
            title="Your account is not authorised for AURA",
            code="NOT_WHITELISTED",
            status=403,
            details=[detail],
        ),
    )


class ExtensionAuthService:
    def __init__(
        self,
        install_repo: InstallRepository,
        token_repo: ExtensionTokenRepository,
    ):
        self.install_repo = install_repo
        self.token_repo = token_repo

    async def register(
        self,
        *,
        google_access_token: str,
        body_email: str,
        body_sub: str,
        extension_version: str,
        environment_json: dict,
    ) -> tuple[ExtensionInstall, install_token_provider.IssuedToken]:
        # 1. Verify the Google access token via userinfo (10 s timeout).
        try:
            userinfo = await google_verifier.verify_access_token(
                google_access_token
            )
        except google_verifier.InvalidAudience:
            raise _google_auth_failed(
                "Token audience does not match configured client_id"
            )

        google_sub = userinfo.get("sub")
        google_email = userinfo.get("email")
        google_email_verified = userinfo.get("email_verified", False)

        if not google_sub or not google_email:
            raise _google_auth_failed("Google response missing identity fields")

        # 2. Body <-> userinfo consistency.
        if body_sub != google_sub:
            raise _google_auth_failed("sub does not match Google account")
        if body_email.lower() != google_email.lower():
            raise _google_auth_failed("email does not match Google account")
        if google_email_verified is False:
            # Explicit False from Google — missing is treated as unknown/ok
            # (the field is optional on userinfo v3).
            raise _google_auth_failed("Google account email is not verified")

        # 3. Allow-list / blocklist evaluation (§10).
        verdict = allow_list.evaluate(google_email)
        if not verdict.allowed:
            raise _not_whitelisted(verdict.reason or "not permitted")

        # 4. Upsert install keyed by google_sub.
        install = await self.install_repo.get_by_sub(google_sub)
        if install is None:
            install = await self.install_repo.create(
                ExtensionInstall(
                    google_sub=google_sub,
                    email=google_email,
                    status=InstallStatus.ACTIVE,
                    extension_version=extension_version,
                    environment_json=environment_json,
                )
            )
            outcome = "registered"
        else:
            if install.status == InstallStatus.BLACKLISTED:
                raise _not_whitelisted("Install has been blacklisted")
            await self.install_repo.update(
                install,
                {
                    "email": google_email,
                    "extension_version": extension_version,
                    "environment_json": environment_json,
                },
            )
            # Register revokes any existing tokens — the extension replaces
            # whatever token it holds locally. §8.2.
            await self.token_repo.revoke_all_for_install(
                install.id, reason="reregistered"
            )
            outcome = "re-registered"

        # 5. Issue fresh token.
        issued = await install_token_provider.issue_token(
            install.id, self.token_repo
        )

        logger.info(
            "Extension register OK: install_id=%s email_domain=%s google_sub=%s outcome=%s",
            install.id,
            _domain_of(google_email),
            _truncate_sub(google_sub),
            outcome,
        )

        return install, issued

    async def renew(
        self, *, install: ExtensionInstall, current_token_hash: str
    ) -> install_token_provider.IssuedToken:
        issued = await install_token_provider.rotate_token(
            install_id=install.id,
            current_token_hash=current_token_hash,
            token_repo=self.token_repo,
            reason="renewed",
        )
        logger.info(
            "Extension token renewed: install_id=%s email_domain=%s",
            install.id,
            _domain_of(install.email),
        )
        return issued

    async def logout(
        self, *, install: ExtensionInstall, current_token_hash: str
    ) -> None:
        # Idempotent — if the token is already revoked, ``revoke_by_hash``
        # simply no-ops on the already-revoked row.
        await self.token_repo.revoke_by_hash(
            current_token_hash, reason="logout"
        )
        logger.info(
            "Extension logout: install_id=%s email_domain=%s",
            install.id,
            _domain_of(install.email),
        )
