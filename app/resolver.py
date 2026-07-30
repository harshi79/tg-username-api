"""Advanced input resolver for v2 endpoint.

Classifies input as either a *username* (reusing the existing v1 checker) or
a *numeric user ID*.  Telegram numeric IDs cannot be publicly resolved to a
profile without an authenticated session — the endpoint validates only
syntactic correctness.

Supported input forms:

    durov                        → username
    @durov                       → username
    https://t.me/durov           → username
    t.me/durov                   → username
    yori                         → username
    7728424218                   → user_id
    tg://openmessage?user_id=7728424218  → user_id

Investigation findings (2026-07-30):
------------------------------------
- ``tg://openmessage?user_id=<id>`` is a local-client deep link: it instructs
  the Telegram app to open a message view for the given user.  No server-side
  resolution occurs — the client looks up the ID among its known peers using
  the local access hash.
- There is no legitimate public API (Telegram or otherwise) that resolves a
  numeric user ID to a username or profile without an authenticated session.
- ``t.me/<numeric_id>`` does not work as a public page URL.
- Therefore, while syntactically valid numeric IDs are accepted and validated,
  actual profile resolution is **not** possible through the public mechanisms
  available to this API.
"""

from __future__ import annotations

import re
from enum import Enum
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Input classification
# ---------------------------------------------------------------------------


class InputType(str, Enum):
    USERNAME = "username"
    USER_ID = "user_id"


class ResolvedInput(BaseModel):
    """Result of parsing and classifying a raw query string."""

    input: str = Field(description="The raw input exactly as received.")
    normalized: str = Field(description="Normalized form: bare username or user ID.")
    input_type: InputType = Field(description="Classification of the input.")
    valid: bool = Field(description="Whether the input is syntactically valid.")
    error: str | None = Field(default=None, description="Validation error message when invalid.")


# Telegram user IDs are positive 32-bit or 64-bit integers.
# Real user IDs are positive.  Bots/Chats can also have IDs.
# Accept up to 64-bit range for forward compatibility.
_ID_RE = re.compile(r"^\d{1,20}$")
_NEGATIVE_NUM_RE = re.compile(r"^-\d+$")
_LONG_DIGITS_RE = re.compile(r"^\d{21,}$")

_TME_HOSTS = {"t.me", "telegram.me", "www.t.me", "www.telegram.me", "telegram.dog"}


def classify_query(raw: object) -> ResolvedInput:
    """Parse and classify a raw query string.

    Returns a ``ResolvedInput`` with ``valid=True`` when the input is
    syntactically acceptable.  *Does not* mean the user ID corresponds to a
    real Telegram account — that cannot be verified publicly.
    """
    if not isinstance(raw, str):
        return ResolvedInput(
            input=str(raw),
            normalized="",
            input_type=InputType.USER_ID,
            valid=False,
            error="query must be a string",
        )

    original = raw
    value = raw.strip()
    if not value:
        return ResolvedInput(
            input=original,
            normalized="",
            input_type=InputType.USER_ID,
            valid=False,
            error="query is empty",
        )

    # --- tg://openmessage?user_id=<id> -------------------------------------
    if value.lower().startswith("tg://openmessage"):
        parsed = urlparse(value)
        if parsed.scheme.lower() != "tg":
            return _invalid(original, "invalid URI scheme")
        if parsed.hostname and parsed.hostname.lower() != "openmessage":
            return _invalid(original, f"unknown tg:// target: {parsed.hostname}")
        qs = parse_qs(parsed.query)
        uid_list = qs.get("user_id", [])
        if not uid_list:
            return _invalid(original, "missing user_id parameter in tg://openmessage link")
        uid = uid_list[0].strip()
        if not _ID_RE.match(uid):
            return _invalid(original, "user_id parameter is not a valid numeric ID")
        if _is_suspicious_id(uid):
            return _invalid(original, "user_id value is out of acceptable range")
        return ResolvedInput(
            input=original,
            normalized=uid,
            input_type=InputType.USER_ID,
            valid=True,
        )

    # --- Detect t.me URL (username) ----------------------------------------
    if "://" in value:
        lowered = value.lower()
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()
        if host in _TME_HOSTS:
            parts = [p for p in parsed.path.split("/") if p]
            if not parts:
                return _invalid(original, "t.me URL without a username path")
            candidate = parts[0]
            if parts[0].lower() == "s" and len(parts) > 1:
                candidate = parts[1]
            return _username_result(original, candidate)

    # --- Detect bare t.me/xxx without scheme -------------------------------
    first_slash = value.find("/")
    if first_slash > 0:
        host_candidate = value[:first_slash].lower()
        if host_candidate in _TME_HOSTS:
            parts = [p for p in value.split("/") if p]
            if len(parts) >= 2:
                candidate = parts[1]
                if parts[1].lower() in {"s"} and len(parts) > 2:
                    candidate = parts[2]
                return _username_result(original, candidate)

    # --- tg://resolve?domain=<name> (username deep link) --------------------
    if value.lower().startswith("tg://"):
        parsed = urlparse(value)
        if parsed.scheme.lower() != "tg":
            return _invalid(original, "invalid URI scheme")
        qs = parse_qs(parsed.query)
        domain = qs.get("domain", [""])[0].strip()
        if domain:
            return _username_result(original, domain)
        return _invalid(original, "could not extract username from deep link")

    # --- Numeric ID (bare digits) ------------------------------------------
    stripped = value.lstrip("@").strip()
    if _NEGATIVE_NUM_RE.match(stripped):
        return _invalid(original, "numeric ID must be a positive number")
    if _LONG_DIGITS_RE.match(stripped):
        return _invalid(original, "numeric ID is too long")
    if _ID_RE.match(stripped):
        if _is_suspicious_id(stripped):
            return _invalid(original, "numeric ID is out of acceptable range")
        return ResolvedInput(
            input=original,
            normalized=stripped,
            input_type=InputType.USER_ID,
            valid=True,
        )

    # --- Username (treat as @username) -------------------------------------
    candidate = stripped.split("?")[0].split("#")[0]
    if "://" in candidate.lower():
        host = (urlparse(candidate).netloc or "").lower()
        if host and host not in _TME_HOSTS:
            return _invalid(original, "input is a URL but not a recognised Telegram link format")
    return _username_result(original, candidate)


def _username_result(raw: str, candidate: str) -> ResolvedInput:
    """Return a username classification (validation deferred to v1 checker)."""
    normalized = candidate.strip().lstrip("@").strip().lower()
    return ResolvedInput(
        input=raw,
        normalized=normalized,
        input_type=InputType.USERNAME,
        valid=True,
    )


def _invalid(raw: str, msg: str) -> ResolvedInput:
    return ResolvedInput(
        input=raw,
        normalized="",
        input_type=InputType.USER_ID,
        valid=False,
        error=msg,
    )


def _is_suspicious_id(uid: str) -> bool:
    """Reject zero, negative-like, or absurdly large values."""
    try:
        val = int(uid)
    except ValueError:
        return True
    if val <= 0:
        return True
    if val > 9007199254740991:
        return True
    return False
