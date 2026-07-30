"""Username normalization and validation.

Accepted input formats (all normalized to a bare lowercase username):

    durov
    @durov
    t.me/durov
    https://t.me/durov
    https://telegram.me/durov
    tg://resolve?domain=durov

Telegram's public rules for regular usernames (a-z, 0-9, underscore, 5-32
characters) are enforced *before* any network request is made, so obviously
invalid input never reaches Telegram or Fragment.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import ValidationResult

# Publicly documented constraints for Telegram usernames.
MIN_LENGTH = 5
MAX_LENGTH = 32
_ALLOWED_CHARS = re.compile(r"^[a-z0-9_]+$")

_TME_HOSTS = {"t.me", "telegram.me", "www.t.me", "www.telegram.me", "telegram.dog"}
_RESERVED_PREFIXES = {"s", "c", "joinchat", "share", "proxy", "socks", "iv", "addstickers", "addemoji", "setlanguage", "confirmemail", "nfc"}


def _strip_url(raw: str) -> str:
    """Extract a username candidate from t.me-style URLs / deep links, or
    return the raw string unchanged when it does not look like a URL."""

    value = raw.strip()

    # tg://resolve?domain=<name> and tg://resolve?domain=<name>&...
    if value.lower().startswith("tg://"):
        parsed = urlparse(value)
        qs = parse_qs(parsed.query)
        domain = qs.get("domain", [""])[0]
        return domain or value

    # t.me/<name>, https://t.me/<name>, telegram.me/<name> (+ optional paths)
    candidate = value
    has_scheme = "://" in candidate
    host_like = candidate.lower().split("/")[0] if not has_scheme else None

    if has_scheme:
        parsed = urlparse(candidate)
        host = (parsed.netloc or "").lower()
        if host in _TME_HOSTS:
            parts = [p for p in parsed.path.split("/") if p]
            if not parts:
                return ""
            # t.me/s/<name> is the public channel preview path.
            if parts[0].lower() in {"s"} and len(parts) > 1:
                return parts[1]
            return parts[0]
        # A URL for some other host is not a username.
        return value

    if host_like is not None and host_like in _TME_HOSTS:
        parts = [p for p in value.split("/") if p]
        if len(parts) >= 2:
            if parts[1].lower() in {"s"} and len(parts) > 2:
                return parts[2]
            return parts[1]
        return ""

    return value


def normalize_username(raw: str) -> str:
    """Best-effort normalization: strips URL/@ wrappers and lowercases."""
    candidate = _strip_url(raw).strip().lstrip("@").strip().rstrip("/")
    # drop anything after a query fragment accidentally included
    candidate = candidate.split("?")[0].split("#")[0]
    return candidate.lower()


def validate_username(raw: object) -> ValidationResult:
    """Validate a username *before* any network request.

    Returns a ValidationResult with the normalized form (when derivable) and a
    precise reason when invalid.
    """

    if not isinstance(raw, str):
        return ValidationResult(valid=False, input=str(raw), normalized=None, reason="username must be a string")

    original = raw
    value = raw.strip()
    if not value:
        return ValidationResult(valid=False, input=original, normalized=None, reason="username is empty")

    # Reject clearly foreign URLs with a precise reason instead of a generic
    # character-set error.
    lowered = value.lower()
    if "://" in lowered and not lowered.startswith("tg://"):
        host = (urlparse(value).netloc or "").lower()
        if host and host not in _TME_HOSTS:
            return ValidationResult(
                valid=False,
                input=original,
                normalized=None,
                reason="input is a URL but not a t.me / telegram.me link",
            )

    normalized = normalize_username(value)
    if not normalized:
        return ValidationResult(valid=False, input=original, normalized=None, reason="no username could be extracted from the input")

    if len(normalized) < MIN_LENGTH:
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason=f"username is too short ({len(normalized)} chars); Telegram usernames are at least {MIN_LENGTH} characters",
        )
    if len(normalized) > MAX_LENGTH:
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason=f"username is too long ({len(normalized)} chars); Telegram usernames are at most {MAX_LENGTH} characters",
        )
    if not _ALLOWED_CHARS.match(normalized):
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason="username may only contain letters (a-z), digits (0-9) and underscores",
        )
    if normalized[0] == "_" or normalized[-1] == "_":
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason="username must not start or end with an underscore",
        )
    if not normalized[0].isalpha():
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason="username must start with a letter",
        )
    if normalized.split("/")[0].lower() in _RESERVED_PREFIXES and "/" in normalized:
        # defensive: slashes should already be gone, treat as invalid format
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason="username contains reserved URL path structure",
        )

    return ValidationResult(valid=True, input=original, normalized=normalized, reason=None)
