"""Username normalization and validation.

Accepted input formats (all normalized to a bare lowercase username):

    durov
    @durov
    t.me/durov
    https://t.me/durov
    https://telegram.me/durov
    tg://resolve?domain=durov

Validation is split into three layers:

1. **Input validity** (``valid``) — is the input parseable into a normalized
   username at all?  Non-strings, empty strings, and foreign URLs are rejected
   immediately with no upstream requests.

2. **Telegram eligibility** (``telegram_eligible``) — does the username satisfy
   Telegram's public rules for regular usernames (5-32 chars, a-z, 0-9, _,
   starts with a letter, no leading/trailing underscore)?  A username that is
   *parseable* but too short for Telegram (e.g. 4-char ``yori``) is **not**
   globally invalid — it simply cannot be checked on Telegram and is forwarded
   to Fragment.

3. **Fragment eligibility** (``fragment_eligible``) — does the username qualify
   for a Fragment collectible lookup?  Fragment's observed minimum is **4**
   characters (verified live 2026-07-30: ``yori`` has a dedicated
   fragment.com/username/yori page with a minimum bid of 5,609 TON).  3-char
   and shorter strings do not produce dedicated Fragment pages and are skipped.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from .models import ValidationResult

# Publicly documented constraints for Telegram usernames.
TG_MIN_LENGTH = 5
TG_MAX_LENGTH = 32

# Fragment minimum is 4 chars (verified live: yori has a dedicated Fragment
# page at 4 chars; abc redirects to search at 3 chars).
FRAGMENT_MIN_LENGTH = 4
FRAGMENT_MAX_LENGTH = 32

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


# ---------------------------------------------------------------------------
# Global input validation (before any upstream request)
# ---------------------------------------------------------------------------

def validate_username(raw: object) -> ValidationResult:
    """Validate and normalise the *raw input string*.

    Returns ``ValidationResult(valid=True)`` when the input can be parsed into
    a bare lowercase username candidate.  *Does not* enforce Telegram's length
    or character rules — those are split into ``telegram_eligible`` below so
    that short Fragment-compatible names (e.g. the 4-char ``yori``) are still
    forwarded to the Fragment adapter.

    Returns ``valid=False`` only when:
    * input is not a string
    * input is empty
    * input is a URL to a non-``t.me`` host
    * no username could be extracted
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

    # Basic character check — usernames that contain characters outside
    # a-z, 0-9, _ are globally invalid (neither Telegram nor Fragment
    # accepts them).
    if not _ALLOWED_CHARS.match(normalized):
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason="username may only contain letters (a-z), digits (0-9) and underscores",
        )

    if normalized.split("/")[0].lower() in _RESERVED_PREFIXES and "/" in normalized:
        return ValidationResult(
            valid=False,
            input=original,
            normalized=normalized,
            reason="username contains reserved URL path structure",
        )

    # The input is parseable — now determine eligibility for each source.
    tg_eligible, _tg_reason = telegram_eligible(normalized)
    fr_eligible, _fr_reason = fragment_eligible(normalized)

    return ValidationResult(
        valid=True,
        input=original,
        normalized=normalized,
        reason=None,
        telegram_eligible=tg_eligible,
        fragment_eligible=fr_eligible,
    )


# ---------------------------------------------------------------------------
# Telegram eligibility (5-32 chars, letters/digits/underscore, starts letter,
# no leading/trailing underscore)
# ---------------------------------------------------------------------------

def telegram_eligible(normalized: str) -> tuple[bool, str]:
    """Check whether *normalized* could be a valid Telegram username.

    Returns ``(True, "")`` or ``(False, reason_string)``.
    """
    length = len(normalized)
    if length < TG_MIN_LENGTH:
        return False, f"username is too short ({length} chars); Telegram usernames are at least {TG_MIN_LENGTH} characters"
    if length > TG_MAX_LENGTH:
        return False, f"username is too long ({length} chars); Telegram usernames are at most {TG_MAX_LENGTH} characters"
    if normalized[0] == "_" or normalized[-1] == "_":
        return False, "username must not start or end with an underscore"
    if not normalized[0].isalpha():
        return False, "username must start with a letter"
    return True, ""


# ---------------------------------------------------------------------------
# Fragment eligibility (4-32 chars, letters/digits/underscore)
# ---------------------------------------------------------------------------

def fragment_eligible(normalized: str) -> tuple[bool, str]:
    """Check whether *normalized* could be a Fragment collectible username.

    Fragment's public collectible pages are observed for 4-character names
    (e.g. ``yori``) but not for shorter lengths.  Returns ``(True, "")`` or
    ``(False, reason_string)``.
    """
    length = len(normalized)
    if length < FRAGMENT_MIN_LENGTH:
        return False, f"username is too short ({length} chars); Fragment collectibles start at {FRAGMENT_MIN_LENGTH} characters"
    if length > FRAGMENT_MAX_LENGTH:
        return False, f"username is too long ({length} chars)"
    return True, ""
