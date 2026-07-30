"""Telegram public presence adapter (t.me).

Classification is based *only* on publicly observable behaviour of
``https://t.me/<username>`` verified against the live site on 2026-07-30:

Observed response kinds
------------------------
1. **Rich profile page** (HTTP 200 on ``t.me/<u>``) containing public stats:
   ``... subscribers`` + ``t.me/s/<u>`` preview link .............. channel
   ``... members, ... online`` ................................... group
   title ``Telegram: Launch @<u>`` / ``... monthly users`` ....... bot
   => the username **resolves** (``exists=True``) and the entity type is known.

2. **Bare contact page** (HTTP 200) — *"If you have Telegram, you can contact
   @x right away"* + a *Send Message* button and nothing else.
   Verified: a definitely-registered user (``@support``) and a random free
   string render **the identical** bare page. Public signals cannot
   distinguish the two cases, therefore ``exists=None`` (indeterminate).
   A bare page must never be treated as proof of availability.

3. **HTTP 404** .................... username does not currently resolve.

4. **Redirect chain ending at telegram.org** — Telegram serves no page for
   the handle => does not currently resolve (observed for handles Telegram
   itself rejects).

5. **Redirect to ``tg://resolve?domain=<u>``** — no public web page is
   served; public existence cannot be determined on the web (indeterminate).

6. **429 / 5xx / network errors / timeouts** => error, ``exists=None``.
   A failure is *never* interpreted as availability.

If Telegram changes these pages, the adapter degrades to
``page_kind=unrecognized / exists=None`` instead of guessing.
"""

from __future__ import annotations

import html as ihtml
import logging
import re
from typing import Optional
from urllib.parse import urlparse

from .config import settings
from .http import HttpManager
from .models import EntityType, ErrorCode, ErrorInfo, TelegramPageKind, TelegramResult

logger = logging.getLogger(__name__)

# --- marker patterns (all observed on live t.me pages, 2026-07) ------------

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_TITLE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
    re.IGNORECASE,
)

_CONTACT_TITLE_RE = re.compile(r"Telegram:\s*Contact\s*@", re.IGNORECASE)
_VIEW_TITLE_RE = re.compile(r"Telegram:\s*View\s*@", re.IGNORECASE)
_LAUNCH_TITLE_RE = re.compile(r"Telegram:\s*Launch\s*@", re.IGNORECASE)

_COUNTERS_RE = re.compile(
    r"([\d][\d\s.,\u00a0]*)\s*(monthly users|subscribers|members|online)",
    re.IGNORECASE,
)
_PREVIEW_LINK_RE = re.compile(r"href=[\"']https?://t\.me/s/", re.IGNORECASE)
_RESOLVE_LINK_RE = re.compile(r"tg://resolve\?domain=", re.IGNORECASE)
_PAGE_TITLE_BLOCK_RE = re.compile(
    r'class="[^"]*tgme_page_title[^"]*"[^>]*>\s*<span[^>]*>(.*?)</span>', re.IGNORECASE | re.DOTALL
)
_PAGE_PHOTO_RE = re.compile(r'tgme_page_photo', re.IGNORECASE)

_CONTACT_PHRASE = "you can contact"
_JOIN_PHRASE = "you can view and join"
_LAUNCH_PHRASE = "you can launch"
_POSTS_PHRASE = "you can view posts"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")


def _visible_text(html: str) -> str:
    """Cheap tag-stripping sufficient for phrase matching (no BS4 dependency)."""
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", without_scripts)
    return _WS_RE.sub(" ", ihtml.unescape(text)).strip()


def _extract_title(html: str) -> Optional[str]:
    for pattern in (_OG_TITLE_RE, _OG_TITLE_RE_ALT, _TITLE_RE):
        match = pattern.search(html)
        if match:
            return _WS_RE.sub(" ", ihtml.unescape(match.group(1))).strip()
    return None


class TelegramAdapter:
    """Determines whether a username publicly resolves on Telegram."""

    source_name = "telegram"

    def __init__(self, http: HttpManager) -> None:
        self._http = http
        self._base = settings.telegram_base_url

    async def check(self, username: str) -> TelegramResult:
        url = f"{self._base}/{username}"
        result = TelegramResult(checked=True, public_url=url)

        response = await self._http.fetch(url)
        result.http_status = response.status_code
        result.final_url = response.final_url

        if response.error_kind == "rate_limited":
            result.page_kind = TelegramPageKind.RATE_LIMITED
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_RATE_LIMIT, message="Telegram rate limited the lookup", source=self.source_name, retryable=True)
            return result
        if response.error_kind == "server_error":
            result.page_kind = TelegramPageKind.SERVER_ERROR
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_SERVER_ERROR, message=f"Telegram returned HTTP {response.status_code}", source=self.source_name, retryable=True)
            return result
        if not response.ok:
            return self._with_error(result, response)

        # --- redirect outcomes ------------------------------------------------
        if response.non_http_redirect:
            result.page_kind = TelegramPageKind.DEEP_LINK_REDIRECT
            result.final_url = response.non_http_redirect
            result.exists = None
            result.evidence.append(
                f"Telegram redirected the web page to '{response.non_http_redirect}' (no public web page served)"
            )
            return result

        final = response.final_url or url
        final_host = (urlparse(final).hostname or "").lower()
        final_path = urlparse(final).path.strip("/").lower()

        if final_host.endswith("telegram.org") and final_host != "t.me":
            result.page_kind = TelegramPageKind.REDIRECT_TO_TELEGRAM_ORG
            result.exists = False
            result.evidence.append(f"t.me redirected to {final} (Telegram serves no public page for this handle)")
            return result

        if response.redirect_chain and final_host == "t.me" and final_path == "":
            result.page_kind = TelegramPageKind.REDIRECT_TO_TELEGRAM_ORG
            result.exists = False
            result.evidence.append(f"t.me redirected to the site root ({final})")
            return result

        # --- status-based negatives -------------------------------------------
        if response.status_code == 404:
            result.page_kind = TelegramPageKind.NOT_FOUND
            result.exists = False
            result.evidence.append("t.me answered with HTTP 404")
            return result

        if response.status_code != 200:
            result.page_kind = TelegramPageKind.UNRECOGNIZED
            result.exists = None
            result.evidence.append(f"unexpected HTTP status {response.status_code}")
            return result

        return self._classify_page(username, result, response.text)

    # ------------------------------------------------------------------
    def _classify_page(self, username: str, result: TelegramResult, body: str) -> TelegramResult:
        if not body or len(body) < 200:
            result.page_kind = TelegramPageKind.UNRECOGNIZED
            result.exists = None
            result.evidence.append("response body absent or unexpectedly small")
            return result

        title = _extract_title(body) or ""
        text = _visible_text(body)
        lowered = text.lower()

        counters = {label.lower(): value for value, label in _COUNTERS_RE.findall(lowered)}
        has_preview_link = bool(_PREVIEW_LINK_RE.search(body))
        has_resolve_link = bool(_RESOLVE_LINK_RE.search(body))
        title_block = _PAGE_TITLE_BLOCK_RE.search(body)
        display_name = _WS_RE.sub(" ", ihtml.unescape(_TAG_RE.sub("", title_block.group(1)))).strip() if title_block else None
        has_photo = bool(_PAGE_PHOTO_RE.search(body))
        has_contact_phrase = _CONTACT_PHRASE in lowered

        evidence = result.evidence
        if title:
            evidence.append(f"page title: '{title}'")
        if counters:
            evidence.append("public counters: " + ", ".join(f"{v} {k}" for k, v in counters.items()))
        if has_preview_link:
            evidence.append("public channel preview link (t.me/s/...) present")
        if has_photo:
            evidence.append("profile photo block present")
        if display_name:
            evidence.append(f"public display name shown: '{display_name}'")
            result.display_name = display_name

        # --- bot ---------------------------------------------------------------
        if _LAUNCH_TITLE_RE.search(title) or "monthly users" in counters or _LAUNCH_PHRASE in lowered:
            result.page_kind = TelegramPageKind.RICH_PROFILE_PAGE
            result.exists = True
            result.entity_type = EntityType.BOT
            return result

        # --- channel -----------------------------------------------------------
        if "subscribers" in counters or has_preview_link or _POSTS_PHRASE in lowered:
            result.page_kind = TelegramPageKind.RICH_PROFILE_PAGE
            result.exists = True
            result.entity_type = EntityType.CHANNEL
            return result

        # --- group -------------------------------------------------------------
        if "members" in counters or ("members" in lowered and "online" in counters):
            result.page_kind = TelegramPageKind.RICH_PROFILE_PAGE
            result.exists = True
            result.entity_type = EntityType.GROUP
            return result

        if _VIEW_TITLE_RE.search(title) and _JOIN_PHRASE in lowered:
            # "View @" page without counters and without a preview link.
            result.page_kind = TelegramPageKind.RICH_PROFILE_PAGE
            result.exists = True
            result.entity_type = EntityType.UNKNOWN_ENTITY
            evidence.append("resolve page without public stats: entity type not publicly visible")
            return result

        # --- user / ghost pages ------------------------------------------------
        if _CONTACT_TITLE_RE.search(title) or has_contact_phrase:
            rich_artifacts = bool(display_name or has_photo or counters)
            if rich_artifacts:
                result.page_kind = TelegramPageKind.RICH_PROFILE_PAGE
                result.exists = True
                result.entity_type = EntityType.USER
                return result
            result.page_kind = TelegramPageKind.BARE_CONTACT_PAGE
            result.exists = None
            evidence.append(
                "bare 'contact' page only — Telegram renders the identical page for private-profile users "
                "and for unclaimed handles; public presence is indeterminate"
            )
            return result

        # --- resolve link without any context ----------------------------------
        if has_resolve_link:
            result.page_kind = TelegramPageKind.UNRECOGNIZED
            result.exists = None
            evidence.append("only an app resolve link found; page structure not recognized")
            return result

        result.page_kind = TelegramPageKind.UNRECOGNIZED
        result.exists = None
        evidence.append("page did not match any known public t.me layout")
        return result

    # ------------------------------------------------------------------
    def _with_error(self, result: TelegramResult, response) -> TelegramResult:
        if response.error_kind == "timeout":
            result.page_kind = TelegramPageKind.NETWORK_ERROR
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_TIMEOUT, message=response.error_detail or "timeout contacting t.me", source=self.source_name, retryable=True)
        else:
            result.page_kind = TelegramPageKind.NETWORK_ERROR
            result.error = ErrorInfo(code=ErrorCode.NETWORK_ERROR, message=response.error_detail or "network failure contacting t.me", source=self.source_name, retryable=True)
        result.exists = None
        result.evidence.append("the lookup failed at network level — failures never imply availability")
        return result
