"""Unit tests for validation, adapters and the conservative decision matrix."""

from __future__ import annotations

import pytest

from app.checker import build_characteristics, build_heuristic_score
from app.models import (
    EntityType,
    ErrorCode,
    FragmentListingState,
    OverallStatus,
    TelegramPageKind,
)
from app.validators import normalize_username, validate_username


# ---------------------------------------------------------------------------
# normalization & validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("durov", "durov"),
        ("@durov", "durov"),
        ("@@durov", "durov"),
        ("DUROV", "durov"),
        ("https://t.me/durov", "durov"),
        ("http://t.me/durov", "durov"),
        ("t.me/durov", "durov"),
        ("https://t.me/durov/", "durov"),
        ("https://t.me/durov/123", "durov"),
        ("https://t.me/s/durov", "durov"),
        ("https://telegram.me/durov", "durov"),
        ("tg://resolve?domain=durov", "durov"),
        ("  @BotFather  ", "botfather"),
    ],
)
def test_normalize_formats(raw: str, expected: str) -> None:
    assert normalize_username(raw) == expected
    assert validate_username(raw).normalized == expected


@pytest.mark.parametrize(
    "raw,reason_part",
    [
        ("", "empty"),
        ("duro", "too short"),
        ("d" * 33, "too long"),
        ("1durov", "must start with a letter"),
        ("_durov", "start or end"),
        ("durov_", "start or end"),
        ("du rov", "letters (a-z), digits (0-9) and underscores"),
        ("duro-v", "letters (a-z), digits (0-9) and underscores"),
        ("https://example.com/foo", "not a t.me"),
    ],
)
def test_invalid_usernames(raw: str, reason_part: str) -> None:
    result = validate_username(raw)
    assert result.valid is False
    assert result.reason is not None and reason_part in result.reason


async def test_validation_never_makes_requests(checker, fake_http) -> None:
    response = await checker.check_username("a1")
    assert response.result.status == OverallStatus.INVALID
    assert response.telegram.checked is False
    assert response.fragment.checked is False
    assert fake_http.calls == []


# ---------------------------------------------------------------------------
# telegram adapter: observed live states
# ---------------------------------------------------------------------------


async def test_telegram_channel(checker) -> None:
    res = await checker.telegram.check("durov")
    assert res.exists is True
    assert res.entity_type == EntityType.CHANNEL
    assert res.page_kind == TelegramPageKind.RICH_PROFILE_PAGE
    assert res.display_name == "Pavel Durov"


async def test_telegram_group(checker) -> None:
    res = await checker.telegram.check("durovschat")
    assert res.exists is True
    assert res.entity_type == EntityType.GROUP


async def test_telegram_bot(checker) -> None:
    res = await checker.telegram.check("botfather")
    assert res.exists is True
    assert res.entity_type == EntityType.BOT


async def test_bare_contact_page_is_indeterminate(checker) -> None:
    """The most important safety property: a bare 'contact' page must NOT be
    treated as available (registered users render the identical page)."""
    res = await checker.telegram.check("wqxjvkzq")
    assert res.exists is None
    assert res.page_kind == TelegramPageKind.BARE_CONTACT_PAGE
    registered_user = await checker.telegram.check("support")
    assert registered_user.exists is None
    assert registered_user.page_kind == TelegramPageKind.BARE_CONTACT_PAGE


async def test_telegram_404_is_negative(checker) -> None:
    res = await checker.telegram.check("gone404")
    assert res.exists is False
    assert res.page_kind == TelegramPageKind.NOT_FOUND


async def test_telegram_org_redirect_is_negative(checker) -> None:
    res = await checker.telegram.check("orgname")
    assert res.exists is False
    assert res.page_kind == TelegramPageKind.REDIRECT_TO_TELEGRAM_ORG


async def test_telegram_deep_link_is_indeterminate(checker) -> None:
    res = await checker.telegram.check("firexi")
    assert res.exists is None
    assert res.page_kind == TelegramPageKind.DEEP_LINK_REDIRECT


async def test_telegram_garbage_page_is_indeterminate(checker) -> None:
    res = await checker.telegram.check("oddpage")
    assert res.exists is None
    assert res.page_kind == TelegramPageKind.UNRECOGNIZED


async def test_telegram_timeout_is_error_never_negative(checker) -> None:
    res = await checker.telegram.check("flakyuser")
    assert res.exists is None
    assert res.error is not None and res.error.code == ErrorCode.UPSTREAM_TIMEOUT


async def test_telegram_rate_limit_is_error_never_negative(checker) -> None:
    res = await checker.telegram.check("busyuser")
    assert res.exists is None
    assert res.error is not None and res.error.code == ErrorCode.UPSTREAM_RATE_LIMIT


# ---------------------------------------------------------------------------
# fragment adapter: observed live states
# ---------------------------------------------------------------------------


async def test_fragment_taken(checker) -> None:
    res = await checker.fragment.check("durov")
    assert res.found is True
    assert res.status == FragmentListingState.TAKEN
    assert res.collectible is False
    assert res.price is None


async def test_fragment_auction(checker) -> None:
    res = await checker.fragment.check("polymarket")
    assert res.found is True
    assert res.status == FragmentListingState.ON_AUCTION
    assert res.collectible is True
    assert res.auction is not None
    assert res.auction.highest_bid is not None and res.auction.highest_bid.amount == 354900.0
    assert res.auction.minimum_bid is not None and res.auction.minimum_bid.amount == 372645.0
    assert res.auction.buy_now is not None and res.auction.buy_now.amount == 1000000.0
    assert res.price is not None and res.price.amount == 372645.0
    assert res.price.approx_usd == "$530,186"


async def test_fragment_for_sale(checker) -> None:
    res = await checker.fragment.check("scalp")
    assert res.found is True
    assert res.status == FragmentListingState.FOR_SALE
    assert res.price is not None and res.price.amount == 4750.0 and res.price.currency == "TON"
    assert res.price.approx_usd == "$6,755"


async def test_fragment_available(checker) -> None:
    res = await checker.fragment.check("stormed")
    assert res.found is True
    assert res.status == FragmentListingState.AVAILABLE
    assert res.price is not None and res.price.amount == 563.0


async def test_fragment_not_found_via_search_redirect(checker) -> None:
    res = await checker.fragment.check("wqxjvkzq")
    assert res.found is False
    assert res.error is None


async def test_fragment_page_without_badge_is_unknown_not_negative(checker) -> None:
    res = await checker.fragment.check("oddname")
    assert res.found is True
    assert res.status == FragmentListingState.UNKNOWN
    assert res.collectible is None


async def test_fragment_garbage_page_is_error_not_negative(checker) -> None:
    res = await checker.fragment.check("walled")
    assert res.found is None
    assert res.error is not None and res.error.code == ErrorCode.UPSTREAM_UNRECOGNIZED


async def test_fragment_timeout_is_error(checker) -> None:
    res = await checker.fragment.check("flakyser")
    assert res.found is None
    assert res.error is not None and res.error.code == ErrorCode.UPSTREAM_TIMEOUT


# ---------------------------------------------------------------------------
# decision matrix: no false 'available', ever
# ---------------------------------------------------------------------------


async def test_overall_taken_for_channel(checker) -> None:
    res = await checker.check_username("durov")
    assert res.result.status == OverallStatus.TAKEN
    assert res.fragment.checked is False  # fragment not queried when telegram resolves


async def test_overall_404_plus_fragment_empty_is_available(checker) -> None:
    res = await checker.check_username("gone404")
    assert res.result.status == OverallStatus.AVAILABLE
    assert res.telegram.exists is False
    assert res.fragment.found is False


async def test_overall_bare_page_plus_fragment_empty_is_unknown(checker) -> None:
    res = await checker.check_username("wqxjvkzq")
    assert res.result.status == OverallStatus.UNKNOWN
    assert res.telegram.exists is None
    assert res.fragment.found is False


async def test_overall_fragment_collectible_when_tg_negative(checker, fake_http) -> None:
    # telegram clearly negative (org redirect), fragment auction page exists
    from tests.pages import FRAG_AUCTION_HTML

    fake_http.on_fragment("orgname", fake_http.fragment_page("orgname", FRAG_AUCTION_HTML.replace("polymarket", "orgname")))
    res = await checker.check_username("orgname")
    assert res.result.status == OverallStatus.FRAGMENT_COLLECTIBLE


async def test_overall_network_failure_is_unknown_not_available(checker) -> None:
    res = await checker.check_username("flakyuser")
    assert res.result.status == OverallStatus.UNKNOWN
    assert res.result.explanation is not None


async def test_overall_unparsable_fragment_is_unknown(checker, fake_http) -> None:
    # telegram 404 + fragment page found but badge unparsable -> NOT available
    fake_http.on_telegram("oddname", fake_http.telegram_page("oddname", "<html><title>x</title></html>", status=404))
    res = await checker.check_username("oddname")
    assert res.result.status == OverallStatus.UNKNOWN


async def test_result_is_cached(checker, fake_http) -> None:
    first = await checker.check_username("durov")
    second = await checker.check_username("durov")
    assert first.cached is False
    assert second.cached is True
    assert fake_http.calls.count("https://t.me/durov") == 1


# ---------------------------------------------------------------------------
# characteristics & heuristic score
# ---------------------------------------------------------------------------


def test_characteristics() -> None:
    c = build_characteristics("durov")
    assert c.length == 5 and c.digit_count == 0 and c.underscore_count == 0 and c.only_letters
    c2 = build_characteristics("storm_2")
    assert c2.underscore_count == 1 and c2.digit_count == 1 and c2.length == 7


def test_heuristic_score_is_labelled_heuristic() -> None:
    score = build_heuristic_score("durov")
    assert 0 <= score.score <= 100
    assert score.label == "heuristic"
    assert score.factor_notes
