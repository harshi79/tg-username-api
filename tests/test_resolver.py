"""Tests for the v2 input resolver."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.resolver import InputType, classify_query


# ---------------------------------------------------------------------------
# Unit tests for classify_query
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,exp_type,exp_valid,exp_normalized",
    [
        ("durov", "username", True, "durov"),
        ("@durov", "username", True, "durov"),
        ("https://t.me/durov", "username", True, "durov"),
        ("http://t.me/durov", "username", True, "durov"),
        ("t.me/durov", "username", True, "durov"),
        ("yori", "username", True, "yori"),
        ("YORI", "username", True, "yori"),
        ("7728424218", "user_id", True, "7728424218"),
        ("tg://openmessage?user_id=7728424218", "user_id", True, "7728424218"),
        ("tg://openmessage?user_id=1", "user_id", True, "1"),
        ("tg://resolve?domain=durov", "username", True, "durov"),
        # invalid
        ("", "user_id", False, ""),
        ("0", "user_id", False, ""),
        ("-1", "user_id", False, ""),
        ("https://evil.com/foo", "user_id", False, ""),
        (None, "user_id", False, ""),  # type: ignore[arg-type]
        # very large number
        ("9999999999999999999999999", "user_id", False, ""),
    ],
)
def test_classify_query(raw, exp_type, exp_valid, exp_normalized) -> None:
    result = classify_query(raw)
    assert result.input_type.value == exp_type, f"expected {exp_type}, got {result.input_type}"
    assert result.valid == exp_valid, f"expected valid={exp_valid}, got valid={result.valid}"
    assert result.normalized == exp_normalized, f"expected normalized={exp_normalized!r}, got {result.normalized!r}"


# ---------------------------------------------------------------------------
# API-level tests for /api/v2/resolve
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(fake_http):
    from app.checker import UsernameChecker

    # Register yori's fragment page so the v1 check works when called through v2
    from tests.pages import FRAG_AVAILABLE_HTML
    fake_http.on_fragment("yori", fake_http.fragment_page("yori", FRAG_AVAILABLE_HTML.replace("stormed", "yori")))

    with TestClient(app) as test_client:
        app.state.checker = UsernameChecker(fake_http)
        yield test_client, fake_http


def test_resolve_username(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v2/resolve", params={"query": "@yori"}).json()
    assert body["success"] is True
    assert body["input_type"] == "username"
    assert body["normalized"] == "yori"
    assert body["v1_check"] is not None
    assert body["result"]["status"] == "username_result"


def test_resolve_numeric_id(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v2/resolve", params={"query": "7728424218"}).json()
    assert body["success"] is True
    assert body["input_type"] == "user_id"
    assert body["normalized"] == "7728424218"
    assert body["user_id"] == "7728424218"
    assert body["resolved"] is False
    assert body["result"]["status"] == "unresolved"
    # Numeric IDs must never have a v1_check (Fragment is username-only)
    assert body.get("v1_check") is None


def test_resolve_deep_link(client) -> None:
    test_client, _ = client
    body = test_client.get(
        "/api/v2/resolve",
        params={"query": "tg://openmessage?user_id=7728424218"},
    ).json()
    assert body["success"] is True
    assert body["input_type"] == "user_id"
    assert body["normalized"] == "7728424218"
    assert body["resolved"] is False


def test_resolve_invalid_input(client) -> None:
    test_client, _ = client
    # Negative number → invalid
    body = test_client.get("/api/v2/resolve", params={"query": "-1"}).json()
    assert body["success"] is True
    # Should have an invalid/unresolved result
    assert body["result"]["status"] in ("invalid", "unresolved")
    assert body.get("v1_check") is None
    # No fragment for invalid input
    assert body["resolved"] is False


def test_resolve_missing_query(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/v2/resolve")
    assert response.status_code == 422


def test_v1_unchanged(client) -> None:
    """Verify v1 check endpoint still works."""
    test_client, fake_http = client
    body = test_client.get("/api/v1/check", params={"username": "yori"}).json()
    assert body["success"] is True
    assert body["username"] == "yori"
