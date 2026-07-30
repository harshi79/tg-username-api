"""Rate-limit behavior tests: 25 req/IP/min on /api/*, website exempt."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models import ErrorCode
from app.ratelimit import InMemoryRateLimitBackend, client_ip


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


LIMIT = settings.rate_limit_requests_per_minute  # production default: 25


def test_first_25_requests_allowed_26th_blocked(client) -> None:
    for i in range(LIMIT):
        response = client.get("/api/health")
        assert response.status_code == 200, f"request {i + 1} should be allowed"
        assert response.json() == {"status": "ok"}

    blocked = client.get("/api/health")
    assert blocked.status_code == 429
    body = blocked.json()
    assert body == {
        "success": False,
        "error": {
            "code": ErrorCode.RATE_LIMIT_EXCEEDED.value,
            "message": "Rate limit exceeded. Try again shortly.",
            "source": None,
            "retryable": None,
        },
    }


def test_rate_limit_headers_present_on_success(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == str(LIMIT)
    assert int(response.headers["X-RateLimit-Remaining"]) == LIMIT - 1
    assert int(response.headers["X-RateLimit-Reset"]) > 0


def test_rate_limit_headers_on_429(client) -> None:
    for _ in range(LIMIT):
        client.get("/api/health")
    blocked = client.get("/api/health")
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == str(LIMIT)
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked.headers["X-RateLimit-Reset"]) > 0
    assert int(blocked.headers["Retry-After"]) >= 1


def test_website_routes_do_not_consume_api_quota(client) -> None:
    # hammer website + static far beyond the API quota
    for _ in range(LIMIT + 10):
        assert client.get("/").status_code == 200
        assert client.get("/tester").status_code == 200
        assert client.get("/docs").status_code == 200
    assert client.get("/static/site.css").status_code == 200
    assert client.get("/swagger").status_code == 200
    assert client.get("/openapi.json").status_code == 200

    # full API quota still untouched
    response = client.get("/api/health")
    assert response.status_code == 200
    assert int(response.headers["X-RateLimit-Remaining"]) == LIMIT - 1


def test_v1_endpoints_share_the_ip_bucket(client) -> None:
    for _ in range(LIMIT):
        assert client.get("/api/v1/check", params={"username": "a1"}).status_code == 200
    blocked = client.get("/api/health")
    assert blocked.status_code == 429


# ---------------------------------------------------------------------------
# unit-level backend behaviour
# ---------------------------------------------------------------------------


def test_inmemory_backend_windows() -> None:
    backend = InMemoryRateLimitBackend()
    t0 = 60_000.5
    for _ in range(3):
        outcome = backend.hit("ip:1.2.3.4", limit=3, window_seconds=60, now=t0)
        assert outcome.allowed
    outcome = backend.hit("ip:1.2.3.4", limit=3, window_seconds=60, now=t0)
    assert not outcome.allowed
    assert outcome.retry_after >= 1
    # next fixed window resets the budget
    outcome = backend.hit("ip:1.2.3.4", limit=3, window_seconds=60, now=t0 + 61)
    assert outcome.allowed


def test_client_ip_ignores_spoofed_headers_when_not_trusted(monkeypatch) -> None:
    from starlette.requests import Request

    # trust_proxy is a @property on the frozen Settings dataclass -> patch class-level
    request = Request(
        scope={
            "type": "http",
            "headers": [(b"x-forwarded-for", b"9.9.9.9")],
            "client": ("1.2.3.4", 1234),
        }
    )
    monkeypatch.setattr(type(settings), "trust_proxy", property(lambda self: False))
    assert client_ip(request) == "1.2.3.4"

    monkeypatch.setattr(type(settings), "trust_proxy", property(lambda self: True))
    assert client_ip(request) == "9.9.9.9"
