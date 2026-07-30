"""Fragment (fragment.com) public lookup adapter.

Fragment has no documented public API for username lookups, so this adapter
uses only the public website pages exactly as a browser would see them. It was
built and validated against the live Fragment site on 2026-07-30:

* ``GET https://fragment.com/username/<u>`` returns a **dedicated page** when
  Fragment tracks the username. The badge next to the ``<u>.t.me`` heading
  shows the listing state. Observed badges: ``Taken``, ``On auction``,
  ``For sale``, ``Available`` (``Sold``/``Unavailable`` handled defensively).
* When Fragment has **no page**, the request redirects to the homepage search
  (``/?query=<u>``). This is treated as "no Fragment listing", never as
  "username is free on Telegram".
* Price information is extracted *only* when the corresponding labels are
  literally present on the page (``Highest Bid``, ``Minimum Bid``,
  ``Sell Price``, ``Buy for ...``). Amounts are read **column-aligned** from
  the ``<th>/<td>`` pairs of Fragment's data tables so values can never be
  attributed to the wrong label. Amounts are never estimated.
* Countdown values are extracted only if an actual duration string is found.

The adapter never logs in, never bypasses CAPTCHAs/rate limits, and reports
``found=None`` + a structured error whenever the response is blocked, rate
limited, or does not match the known layouts — so upstream changes degrade to
``unknown`` instead of wrong answers.

If Fragment redesigns its pages, update *only* this module.
"""

from __future__ import annotations

import html as ihtml
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

from .config import settings
from .http import HttpManager
from .models import Amount, AuctionInfo, ErrorCode, ErrorInfo, FragmentListingState, FragmentResult

logger = logging.getLogger(__name__)

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_TABLE_RE = re.compile(r"<table[^>]*>(.*?)</table>", re.IGNORECASE | re.DOTALL)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_HEADER_CELL_RE = re.compile(r"<th[^>]*>(.*?)</th>", re.IGNORECASE | re.DOTALL)
_BODY_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)

# Badge candidates in priority order. ``tm-section-header-status`` is the header
# badge container class used by Fragment; if the class is ever renamed, the
# text-based fallback below still finds the badge near the ".t.me" heading.
_BADGE_CLASS_RE = re.compile(
    r'class="[^"]*tm-section-header-status[^"]*"[^>]*>(.*?)</',
    re.IGNORECASE | re.DOTALL,
)
_BADGE_TEXT_RE = re.compile(
    r"\.t\.me\b[^A-Za-z0-9]{0,120}?\b(Taken|On auction|For sale|Available|Sold|Unavailable)\b",
    re.IGNORECASE,
)

_BADGE_MAP = {
    "taken": FragmentListingState.TAKEN,
    "on auction": FragmentListingState.ON_AUCTION,
    "for sale": FragmentListingState.FOR_SALE,
    "available": FragmentListingState.AVAILABLE,
    "sold": FragmentListingState.SOLD,
    "unavailable": FragmentListingState.UNAVAILABLE,
}

_TAKEN_PHRASE = "someone already claimed this username"
_NUMBER_RE = r"(\d[\d,\u00a0\s]*(?:\.\d+)?)"
_USD_RE = re.compile(r"~\s*\$([\d,\u00a0]*(?:\.\d+)?)")
_BUY_FOR_RE = re.compile(r"Buy for\s+" + _NUMBER_RE, re.IGNORECASE)

_COUNTDOWN_RE = re.compile(
    r"(\d+\s+days?(?:\s+\d+\s+hours?)?|\d+\s+hours?(?:\s+\d+\s+minutes?)?|\d+\s+minutes?(?:\s+\d+\s+seconds?)?)",
    re.IGNORECASE,
)


def _clean_text(fragment: str) -> str:
    text = _TAG_RE.sub(" ", fragment)
    return _WS_RE.sub(" ", ihtml.unescape(text)).strip()


def _visible_text(html: str) -> str:
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", html)
    return _clean_text(without_scripts)


def _parse_number(raw: str) -> Optional[float]:
    cleaned = raw.replace(",", "").replace("\u00a0", "").replace(" ", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _amount_from_cell(cell_text: str) -> Optional[Amount]:
    """Parse a TON amount (and optional Fragment-provided ~$ estimate) from a table cell."""
    match = re.search(_NUMBER_RE, cell_text)
    if not match:
        return None
    amount = _parse_number(match.group(1))
    if amount is None:
        return None
    usd_match = _USD_RE.search(cell_text)
    return Amount(amount=amount, currency="TON", approx_usd=f"${usd_match.group(1)}" if usd_match else None)


def _tables(html: str) -> list[tuple[list[str], list[list[str]]]]:
    """Return (headers, rows) for every table: column-aligned raw cell text."""
    tables: list[tuple[list[str], list[list[str]]]] = []
    for table_match in _TABLE_RE.finditer(html):
        block = table_match.group(1)
        headers: list[str] = []
        rows: list[list[str]] = []
        for row_match in _ROW_RE.finditer(block):
            row_html = row_match.group(1)
            header_cells = [_clean_text(c) for c in _HEADER_CELL_RE.findall(row_html)]
            if header_cells:
                headers = header_cells
                continue
            body_cells = [c for c in _BODY_CELL_RE.findall(row_html)]
            if body_cells:
                rows.append(body_cells)
        if headers:
            tables.append((headers, rows))
    return tables


def _table_amount(tables: list[tuple[list[str], list[list[str]]]], label: str, row_index: int = 0) -> Optional[Amount]:
    """Find ``label`` in a table header and parse the amount from the aligned
    cell of row ``row_index``. This is the anti-misattribution mechanism: values
    are only read from the same column as their label."""
    label_lower = label.lower()
    for headers, rows in tables:
        for idx, header in enumerate(headers):
            normalized = header.lower().replace("*", "").strip()
            if normalized == label_lower and len(rows) > row_index and idx < len(rows[row_index]):
                cell_text = _clean_text(rows[row_index][idx])
                return _amount_from_cell(cell_text)
    return None


class FragmentAdapter:
    """Checks the public Fragment listing state of a username."""

    source_name = "fragment"

    def __init__(self, http: HttpManager) -> None:
        self._http = http
        self._base = settings.fragment_base_url

    async def check(self, username: str) -> FragmentResult:
        url = f"{self._base}/username/{username}"
        result = FragmentResult(checked=True)

        response = await self._http.fetch(url)

        if response.error_kind == "rate_limited":
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_RATE_LIMIT, message="Fragment rate limited the lookup", source=self.source_name, retryable=True)
            return result
        if response.error_kind == "server_error":
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_SERVER_ERROR, message=f"Fragment returned HTTP {response.status_code}", source=self.source_name, retryable=True)
            return result
        if not response.ok:
            return self._with_error(result, response)

        if response.status_code == 404:
            result.found = False
            result.evidence.append("fragment.com answered with HTTP 404 for the username page")
            return result

        if response.status_code != 200:
            result.found = None
            result.error = ErrorInfo(
                code=ErrorCode.UPSTREAM_UNRECOGNIZED,
                message=f"Fragment returned unexpected HTTP {response.status_code}",
                source=self.source_name,
                retryable=True,
            )
            return result

        final = response.final_url or url
        final_path = (urlparse(final).path or "/").lower().rstrip("/")
        final_qs = parse_qs(urlparse(final).query)

        # Observed: no dedicated page => redirect to "/?query=<username>".
        if (final_path in {"", "/"}) and "query" in final_qs:
            result.found = False
            result.collectible = None
            result.evidence.append(f"fragment.com has no dedicated page for @{username} (redirected to homepage search)")
            return result

        if not final_path.endswith(f"/username/{username.lower()}"):
            # Defensive: unknown redirect target — do not interpret anything.
            result.found = None
            result.error = ErrorInfo(
                code=ErrorCode.UPSTREAM_UNRECOGNIZED,
                message=f"Fragment redirected to an unrecognized location: {final}",
                source=self.source_name,
                retryable=True,
            )
            return result

        result.url = f"{self._base}/username/{username}"
        return self._parse_username_page(username, result, response.text)

    # ------------------------------------------------------------------
    def _parse_username_page(self, username: str, result: FragmentResult, body: str) -> FragmentResult:
        lowered_body = body.lower() if body else ""
        if not body or len(body) < 200 or ".t.me" not in lowered_body:
            result.found = None
            result.error = ErrorInfo(
                code=ErrorCode.UPSTREAM_UNRECOGNIZED,
                message="Fragment page did not contain the expected public structure (possible anti-bot page or redesign)",
                source=self.source_name,
                retryable=True,
            )
            return result

        result.found = True
        text = _visible_text(body)
        tables = _tables(body)
        evidence = result.evidence

        # --- listing state badge ------------------------------------------------
        badge: Optional[str] = None
        class_match = _BADGE_CLASS_RE.search(body)
        if class_match:
            raw = _clean_text(class_match.group(1))
            if raw.lower() in _BADGE_MAP:
                badge = raw.lower()
                evidence.append(f"Fragment status badge: '{raw}'")
        if badge is None:
            text_match = _BADGE_TEXT_RE.search(text)
            if text_match:
                badge = text_match.group(1).lower()
                evidence.append(f"Fragment status (page text): '{text_match.group(1)}'")

        if badge is None:
            result.status = FragmentListingState.UNKNOWN
            result.collectible = None
            evidence.append("dedicated Fragment page found, but its status badge could not be parsed")
            return result

        result.status = _BADGE_MAP[badge]

        # --- state-specific public information ----------------------------------
        if result.status == FragmentListingState.TAKEN:
            result.collectible = False
            if _TAKEN_PHRASE in text.lower():
                evidence.append("Fragment reports: someone already claimed this username on Telegram (offers possible)")
            return result

        if result.status == FragmentListingState.UNAVAILABLE:
            result.collectible = True
            evidence.append("Fragment marks the username as unavailable (held/minted, not listed for sale)")
            return result

        # auctionable states
        result.collectible = True

        minimum_bid = _table_amount(tables, "Minimum Bid")
        highest_bid = _table_amount(tables, "Highest Bid")
        sell_price = _table_amount(tables, "Sell Price")

        buy_now: Optional[Amount] = None
        buy_match = _BUY_FOR_RE.search(text)
        if buy_match:
            buy_amount = _parse_number(buy_match.group(1))
            if buy_amount is not None:
                buy_now = Amount(amount=buy_amount, currency="TON")

        if result.status == FragmentListingState.ON_AUCTION:
            auction = AuctionInfo(minimum_bid=minimum_bid, highest_bid=highest_bid, buy_now=buy_now)
            auction.ends_in = self._extract_countdown(text)
            result.auction = auction
            result.price = minimum_bid or highest_bid
            if highest_bid:
                evidence.append(f"highest bid publicly shown: {highest_bid.amount} TON")
            if minimum_bid:
                evidence.append(f"minimum bid publicly shown: {minimum_bid.amount} TON")
            if buy_now:
                evidence.append(f"'buy now' price publicly shown: {buy_now.amount} TON")
            if auction.ends_in:
                evidence.append(f"auction ends in: {auction.ends_in}")
        elif result.status == FragmentListingState.FOR_SALE:
            result.price = sell_price or buy_now
            if result.price:
                evidence.append(f"sale price publicly shown: {result.price.amount} TON")
            if buy_now and sell_price and buy_now.amount != sell_price.amount:
                result.auction = AuctionInfo(buy_now=buy_now)
        elif result.status == FragmentListingState.AVAILABLE:
            if "place bid and start auction" in text.lower():
                evidence.append("Fragment shows the username as auctionable (no bids yet)")
            result.price = minimum_bid
            result.auction = AuctionInfo(minimum_bid=minimum_bid) if minimum_bid else None
            if minimum_bid:
                evidence.append(f"minimum bid publicly shown: {minimum_bid.amount} TON")
        elif result.status == FragmentListingState.SOLD:
            last_sale = _table_amount(tables, "Sale price")
            result.price = last_sale
            if last_sale:
                evidence.append(f"last sale price publicly shown: {last_sale.amount} TON")

        if result.price is None:
            evidence.append("no public TON price displayed for this state")
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_countdown(text: str) -> Optional[str]:
        anchor = re.search(r"ends in(.{0,300})", text, re.IGNORECASE | re.DOTALL)
        scope = anchor.group(1) if anchor else text[:6000]
        match = _COUNTDOWN_RE.search(scope)
        if match:
            return _WS_RE.sub(" ", match.group(1)).strip().lower()
        return None

    # ------------------------------------------------------------------
    def _with_error(self, result: FragmentResult, response) -> FragmentResult:
        result.found = None
        if response.error_kind == "timeout":
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_TIMEOUT, message=response.error_detail or "timeout contacting fragment.com", source=self.source_name, retryable=True)
        elif response.status_code in {401, 403}:
            result.error = ErrorInfo(code=ErrorCode.UPSTREAM_BLOCKED, message=f"Fragment refused the request (HTTP {response.status_code}) — the adapter does not bypass access controls", source=self.source_name, retryable=False)
        else:
            result.error = ErrorInfo(code=ErrorCode.NETWORK_ERROR, message=response.error_detail or "network failure contacting fragment.com", source=self.source_name, retryable=True)
        result.evidence.append("the lookup failed at network level — failures never imply availability")
        return result
