"""Allow-list / blocklist evaluation used by register and require_install.

Rules (from EXTENSION_IMPLEMENTATION_STANDARD §10):
- Blocklist is checked first. A blocklisted email/domain is rejected even if
  it also appears on the allowlist.
- If both allowlist_domains and allowlist_emails are empty: allow all.
- If either list is non-empty: the email must match at least one entry across
  both lists.
- Matching is case-insensitive. Domain is the part after the last ``@``.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.configs import extension


@dataclass(frozen=True)
class AllowListResult:
    allowed: bool
    reason: str | None = None


def _domain_of(email: str) -> str | None:
    if "@" not in email:
        return None
    return email.rsplit("@", 1)[1].lower().strip()


def evaluate(email: str) -> AllowListResult:
    email_lower = email.lower().strip()
    domain = _domain_of(email_lower)

    block_emails = {e.lower().strip() for e in extension.blocklist_emails if e}
    block_domains = {d.lower().strip() for d in extension.blocklist_domains if d}

    if email_lower in block_emails:
        return AllowListResult(False, "Email is blocklisted")
    if domain and domain in block_domains:
        return AllowListResult(False, "Domain is blocklisted")

    allow_emails = {e.lower().strip() for e in extension.allowlist_emails if e}
    allow_domains = {d.lower().strip() for d in extension.allowlist_domains if d}

    if not allow_emails and not allow_domains:
        return AllowListResult(True)

    if email_lower in allow_emails:
        return AllowListResult(True)
    if domain and domain in allow_domains:
        return AllowListResult(True)

    return AllowListResult(False, "Email is not on the allow-list")
