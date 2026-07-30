"""API-level integration tests (FastAPI TestClient, fake upstreams)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.checker import UsernameChecker
from app.main import app
from app.models import ErrorCode, OverallStatus


@pytest.fixture()
def client(fake_http):
    with TestClient(app) as test_client:
        app.state.checker = UsernameChecker(fake_http)  # swap in fake upstreams
        yield test_client, fake_http


def test_bulk_max_is_15_and_server_enforced(client) -> None:
    test_client, _ = client
    ok_names = ["durov", "botfather", "durovschat"] * 5  # exactly 15 entries
    response = test_client.post("/api/v1/check/bulk", json={"usernames": ok_names})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["total"] == 15

    response = test_client.post("/api/v1/check/bulk", json={"usernames": ok_names + ["support"]})
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == ErrorCode.PAYLOAD_TOO_LARGE.value
    assert "15" in body["error"]["message"]


def test_health(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_check_taken_channel(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/v1/check", params={"username": "@durov"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["username"] == "durov"
    assert body["validation"]["valid"] is True
    assert body["telegram"]["exists"] is True
    assert body["telegram"]["entity_type"] == "channel"
    assert body["fragment"]["checked"] is False
    assert body["result"]["status"] == "taken"
    assert body["checked_at"]


def test_check_bot(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v1/check", params={"username": "https://t.me/BotFather"}).json()
    assert body["username"] == "botfather"
    assert body["telegram"]["entity_type"] == "bot"
    assert body["result"]["status"] == "taken"


def test_check_invalid_shortcircuits(client) -> None:
    test_client, fake_http = client
    body = test_client.get("/api/v1/check", params={"username": "a1"}).json()
    assert body["success"] is True
    assert body["result"]["status"] == "unknown"
    assert body["validation"]["valid"] is True
    assert body["validation"]["telegram_eligible"] is False
    assert body["validation"]["fragment_eligible"] is False
    assert body["telegram"]["checked"] is False
    assert body["fragment"]["checked"] is False
    assert fake_http.calls == []


def test_check_available(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v1/check", params={"username": "gone404"}).json()
    assert body["result"]["status"] == OverallStatus.AVAILABLE.value


def test_check_fragment_collectible(client) -> None:
    test_client, fake_http = client
    # telegram serves a bare page (indeterminate), fragment has the auction
    fake_http.on_telegram("polymarket", fake_http.telegram_page("polymarket", "<title>Telegram: Contact @polymarket</title><body>If you have <strong>Telegram</strong>, you can contact @polymarket right away.</body>"))
    body = test_client.get("/api/v1/check", params={"username": "polymarket"}).json()
    assert body["result"]["status"] == "fragment_collectible"
    assert body["fragment"]["status"] == "on_auction"
    assert body["fragment"]["price"] == {
        "amount": 372645.0,
        "currency": "TON",
        "approx_usd": "$530,186",
    }
    assert body["fragment"]["auction"]["buy_now"]["amount"] == 1000000.0


def test_check_unknown_when_upstream_fails(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v1/check", params={"username": "flakyuser"}).json()
    assert body["result"]["status"] == "unknown"
    assert body["telegram"]["error"]["code"] == ErrorCode.UPSTREAM_TIMEOUT.value


def test_report_includes_characteristics(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v1/report", params={"username": "durov"}).json()
    assert body["characteristics"]["length"] == 5
    assert body["characteristics"]["digit_count"] == 0
    assert body["heuristic_score"]["label"] == "heuristic"
    assert body["signals"]
    assert body["result"]["status"] == "taken"


def test_bulk_happy_path(client) -> None:
    test_client, fake_http = client
    response = test_client.post(
        "/api/v1/check/bulk",
        json={"usernames": ["yorivex", "@yorixa", "https://t.me/yorzen"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["total"] == 3
    assert [r["username"] for r in body["results"]] == ["yorivex", "yorixa", "yorzen"]
    assert [r["result"]["status"] for r in body["results"]] == ["available", "available", "available"]


def test_bulk_mixed_formats_and_invalid(client) -> None:
    test_client, _ = client
    body = test_client.post(
        "/api/v1/check/bulk",
        json={"usernames": ["durov", "a1", "@botfather", "durov"]},
    ).json()
    assert body["total"] == 4
    statuses = [r["result"]["status"] for r in body["results"]]
    assert statuses[0] == "taken"
    # "a1" is parseable but too short for both Telegram and Fragment → unknown
    assert statuses[1] == "unknown"
    assert statuses[2] == "taken"
    assert statuses[3] == "taken"


def test_bulk_shares_upstream_for_duplicates(client) -> None:
    test_client, fake_http = client
    body = test_client.post(
        "/api/v1/check/bulk",
        json={"usernames": ["durov", "DUROV", "@durov", "https://t.me/durov"]},
    ).json()
    assert body["total"] == 4
    assert fake_http.calls.count("https://t.me/durov") == 1


def test_bulk_too_many(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v1/check/bulk", json={"usernames": [f"user{i:04d}x" for i in range(40)]})
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == ErrorCode.PAYLOAD_TOO_LARGE.value


def test_bulk_exactly_16_rejected(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v1/check/bulk", json={"usernames": [f"user{i:04d}x" for i in range(16)]})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.PAYLOAD_TOO_LARGE.value


def test_bulk_empty_payload_validation_error(client) -> None:
    test_client, _ = client
    response = test_client.post("/api/v1/check/bulk", json={"usernames": []})
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


def test_missing_query_param_is_structured_422(client) -> None:
    test_client, _ = client
    response = test_client.get("/api/v1/check")
    assert response.status_code == 422
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == ErrorCode.VALIDATION_ERROR.value


def test_openapi_documentation_available(client) -> None:
    test_client, _ = client
    spec = test_client.get("/openapi.json").json()
    assert "/api/v1/check" in spec["paths"]
    assert "/api/v1/check/bulk" in spec["paths"]
    assert "/api/v1/report" in spec["paths"]
    assert "/api/health" in spec["paths"]
    assert spec["info"]["title"] == "Telegram Username Intelligence API"
    # website pages must NOT leak into the API schema
    for website_path in ["/", "/tester", "/docs"]:
        assert website_path not in spec["paths"]


def test_never_fabricates_private_profile_info(client) -> None:
    test_client, _ = client
    body = test_client.get("/api/v1/check", params={"username": "support"}).json()
    # a bare user page must not expose a fabricated display name or type
    assert body["telegram"]["display_name"] is None
    assert body["telegram"]["exists"] is None
    assert body["result"]["status"] == "unknown"
