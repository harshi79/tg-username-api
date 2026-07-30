"""Pydantic models for requests and responses.

Every response is fully structured so API consumers never need to parse
free-form strings. Fields that could not be determined are ``None`` (rendered
as JSON ``null``) rather than invented values.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class OverallStatus(str, Enum):
    TAKEN = "taken"
    FRAGMENT_COLLECTIBLE = "fragment_collectible"
    AVAILABLE = "available"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    USERNAME_RESULT = "username_result"
    UNRESOLVED = "unresolved"


class EntityType(str, Enum):
    USER = "user"
    BOT = "bot"
    CHANNEL = "channel"
    GROUP = "group"
    UNKNOWN_ENTITY = "unknown_entity"


class FragmentListingState(str, Enum):
    """Listing state as publicly displayed on Fragment (verified 2026-07)."""

    TAKEN = "taken"              # claimed on Telegram, not minted as collectible (offers possible)
    ON_AUCTION = "on_auction"    # active auction (bids open)
    FOR_SALE = "for_sale"        # fixed-price sale listing
    AVAILABLE = "available"      # auctionable on Fragment (no bids yet, minimum bid shown)
    SOLD = "sold"                # previously sold badge (kept for forward compatibility)
    UNAVAILABLE = "unavailable"  # explicitly not purchasable
    UNKNOWN = "unknown"          # page found but state could not be determined reliably


class ErrorCode(str, Enum):
    INVALID_USERNAME = "invalid_username"
    TELEGRAM_NOT_RESOLVED = "telegram_not_resolved"
    FRAGMENT_NOT_FOUND = "fragment_not_found"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    UPSTREAM_RATE_LIMIT = "upstream_rate_limit"
    UPSTREAM_BLOCKED = "upstream_blocked"
    UPSTREAM_SERVER_ERROR = "upstream_server_error"
    UPSTREAM_UNRECOGNIZED = "upstream_unrecognized_response"
    NETWORK_ERROR = "network_error"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"


class ErrorInfo(BaseModel):
    code: ErrorCode
    message: str
    source: Optional[str] = Field(default=None, description="Upstream source that produced the error.")
    retryable: Optional[bool] = Field(default=None, description="Whether retrying later may succeed.")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    valid: bool
    input: str = Field(description="The raw input exactly as received.")
    normalized: Optional[str] = Field(default=None, description="Normalized lowercase username without '@' or URL parts.")
    reason: Optional[str] = Field(default=None, description="Human readable reason when the input is invalid.")
    telegram_eligible: bool = Field(default=True, description="Whether the username satisfies Telegram's eligibility rules (5-32 chars, a-z0-9_, starts with letter, etc.).")
    fragment_eligible: bool = Field(default=True, description="Whether the username is eligible for Fragment lookup (4-32 chars, a-z0-9_).")


# ---------------------------------------------------------------------------
# Telegram check
# ---------------------------------------------------------------------------


class TelegramPageKind(str, Enum):
    RICH_PROFILE_PAGE = "rich_profile_page"        # channel/group/bot page with public stats
    BARE_CONTACT_PAGE = "bare_contact_page"        # minimal "you can contact @x right away" page (ambiguous)
    DEEP_LINK_REDIRECT = "deep_link_redirect"      # redirected to tg://resolve?domain=...
    REDIRECT_TO_TELEGRAM_ORG = "redirect_to_telegram_org"
    NOT_FOUND = "not_found"                        # explicit HTTP 404
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    UNRECOGNIZED = "unrecognized"


class TelegramResult(BaseModel):
    checked: bool = Field(description="Whether a Telegram lookup was attempted.")
    exists: Optional[bool] = Field(
        default=None,
        description=(
            "true = publicly resolves on Telegram, false = clearly does not resolve, "
            "null = public signals are inconclusive (Telegram shows an ambiguous page "
            "or the check failed). null never means available."
        ),
    )
    entity_type: Optional[EntityType] = Field(default=None, description="Public entity type when detectable.")
    page_kind: Optional[TelegramPageKind] = Field(default=None, description="Which kind of public response Telegram returned.")
    display_name: Optional[str] = Field(default=None, description="Publicly displayed name when visible (never fabricated).")
    public_url: str = Field(description="Canonical public URL that was checked.")
    http_status: Optional[int] = Field(default=None, description="HTTP status of the final response when available.")
    final_url: Optional[str] = Field(default=None, description="Final URL after following redirects.")
    evidence: list[str] = Field(default_factory=list, description="Public signals the classification is based on.")
    error: Optional[ErrorInfo] = None


# ---------------------------------------------------------------------------
# Fragment check
# ---------------------------------------------------------------------------


class Amount(BaseModel):
    amount: float = Field(description="Numeric amount as displayed on Fragment.")
    currency: str = Field(default="TON")
    approx_usd: Optional[str] = Field(default=None, description="Approximate USD value as displayed by Fragment, when shown.")


class AuctionInfo(BaseModel):
    minimum_bid: Optional[Amount] = None
    highest_bid: Optional[Amount] = None
    buy_now: Optional[Amount] = None
    ends_in: Optional[str] = Field(default=None, description="Time remaining text as publicly displayed (e.g. '5 days 13 hours').")


class FragmentResult(BaseModel):
    checked: bool = Field(description="Whether a Fragment lookup was attempted.")
    found: Optional[bool] = Field(
        default=None,
        description="true = Fragment has a dedicated public page for this username, false = it does not, null = could not be determined.",
    )
    collectible: Optional[bool] = Field(
        default=None,
        description="true when Fragment shows the username as a tradable/minted collectible (auction, sale, sold or taken-with-offers).",
    )
    status: Optional[FragmentListingState] = Field(default=None, description="Listing state as publicly displayed on Fragment.")
    price: Optional[Amount] = Field(default=None, description="Main publicly displayed ask (sale price / minimum bid). Never estimated.")
    auction: Optional[AuctionInfo] = Field(default=None, description="Auction details when the username is on auction or auctionable.")
    url: Optional[str] = Field(default=None, description="Public Fragment URL for this username when it exists.")
    evidence: list[str] = Field(default_factory=list)
    error: Optional[ErrorInfo] = None


# ---------------------------------------------------------------------------
# Combined result / top-level responses
# ---------------------------------------------------------------------------


class ResultSummary(BaseModel):
    status: OverallStatus
    explanation: Optional[str] = Field(default=None, description="Human readable explanation of the status decision.")


class CheckResponse(BaseModel):
    success: bool
    username: Optional[str] = Field(default=None, description="Normalized username.")
    validation: ValidationResult
    telegram: TelegramResult
    fragment: FragmentResult
    result: ResultSummary
    cached: bool = Field(default=False, description="Whether this result was served from the short-lived TTL cache.")
    checked_at: str = Field(default_factory=utc_now_iso, description="UTC timestamp of the check (ISO-8601).")


class UsernameCharacteristics(BaseModel):
    length: int
    digit_count: int
    underscore_count: int
    alpha_count: int
    starts_with_letter: bool
    ends_with_letter_or_digit: bool
    has_digits: bool
    has_underscores: bool
    only_letters: bool
    max_repeated_char_run: int = Field(description="Longest run of the same character in a row.")
    unique_characters: int


class HeuristicScore(BaseModel):
    score: int = Field(ge=0, le=100, description="0-100 heuristic desirability score. NOT a market valuation.")
    label: str = Field(default="heuristic", description="Constant marker reminding consumers this is a heuristic.")
    factor_notes: list[str] = Field(default_factory=list, description="Objective factors that influenced the score.")


class ReportResponse(BaseModel):
    success: bool
    username: Optional[str] = None
    validation: ValidationResult
    telegram: TelegramResult
    fragment: FragmentResult
    result: ResultSummary
    characteristics: Optional[UsernameCharacteristics] = Field(default=None, description="Objective username traits (null when invalid).")
    heuristic_score: Optional[HeuristicScore] = Field(
        default=None,
        description="Optional heuristic desirability indicators. Never a market price or valuation.",
    )
    signals: list[str] = Field(default_factory=list, description="All public signals gathered during the check.")
    cached: bool = False
    generated_at: str = Field(default_factory=utc_now_iso)


class BulkRequest(BaseModel):
    usernames: list[str] = Field(min_length=1, description="List of usernames in any accepted format.")

    @field_validator("usernames")
    @classmethod
    def _strip_entries(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("every username must be a string")
            cleaned.append(item.strip())
        return cleaned


class BulkResponse(BaseModel):
    success: bool
    total: int
    results: list[CheckResponse]
    generated_at: str = Field(default_factory=utc_now_iso)


# ---------------------------------------------------------------------------
# Errors / misc
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    success: Literal[False] = False
    error: ErrorInfo


class HealthResponse(BaseModel):
    status: str = "ok"


# ---------------------------------------------------------------------------
# v2 Resolve
# ---------------------------------------------------------------------------


class InputType(str, Enum):
    USERNAME = "username"
    USER_ID = "user_id"


class ResolveV2ResultStatus(str, Enum):
    USERNAME_RESULT = "username_result"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"


class ResolveV2Response(BaseModel):
    success: bool
    input: str = Field(description="The raw input exactly as received.")
    input_type: InputType = Field(description="Whether the input was classified as a username or user_id.")
    normalized: str = Field(description="Normalized form: bare lowercase username or numeric user ID string.")
    v1_check: Optional[CheckResponse] = Field(default=None, description="Reused v1 check result when input was a username.")
    user_id: Optional[str] = Field(default=None, description="The extracted numeric user ID when input_type is user_id.")
    resolved: bool = Field(default=False, description="Whether the ID could be publicly resolved to a profile (always false for numeric IDs).")
    result: ResultSummary = Field(description="Resolution status summary.")
    generated_at: str = Field(default_factory=utc_now_iso)


class RootResponse(BaseModel):
    name: str
    version: str
    description: str
    documentation: dict[str, str]
    endpoints: list[dict[str, str]]
    notes: list[str]
    time: str = Field(default_factory=utc_now_iso)
