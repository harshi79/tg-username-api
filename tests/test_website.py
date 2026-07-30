"""Website surface tests: landing page, tester, custom docs, swagger, static."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_homepage_loads(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    # identity + required content
    assert "TG Username API" in body
    assert "Telegram usernames" in body
    # navigation to all required destinations
    for href in ['href="/"', 'href="/tester"', 'href="/docs"', 'href="/swagger"']:
        assert href in body
    # feature cards + status model
    assert "Fragment Intelligence" in body
    assert "Username + ID Resolution" in body
    assert "Detailed Reports" in body
    assert "Telegram Resolution" in body
    assert "badge-unknown" in body
    # API base URL shown on homepage (canonical domain)
    assert "tg-username-api.vercel.app/api/v1" in body
    # no credentials anywhere
    assert "api_hash" not in body.lower() and "bot_token" not in body.lower()
    # sample request uses canonical domain
    assert "tg-username-api.vercel.app" in body
    # mascot image referenced
    assert "mascot.png" in body
    # Yori Federation present, GitHub not promoted
    assert "yorifederation" in body
    assert "github.com/harshi79/tg-username-api" not in body


def test_tester_loads(client) -> None:
    response = client.get("/tester")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "API Tester" in body
    assert 'id="single-username"' in body
    assert 'id="bulk-usernames"' in body
    assert 'id="bulk-counter"' in body
    assert "15" in body  # bulk maximum visible
    assert 'id="single-submit"' in body  # Check button
    assert "/static/tester.js" in body
    # Resolve tab present
    assert 'id="resolve-query"' in body
    assert "api/v2/resolve" in body


def test_custom_docs_loads(client) -> None:
    response = client.get("/docs")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "TG Username API" in body
    # rate limit contract documented
    assert "25 requests per IP address per minute" in body
    assert "15 usernames" in body
    assert "X-RateLimit-Limit" in body
    # statuses documented
    for status in ["taken", "fragment_collectible", "available", "invalid", "unknown"]:
        assert status in body
    # all endpoints documented with example payloads
    for path in ["/api/v1/check", "/api/v1/report", "/api/v1/check/bulk", "/api/v2/resolve"]:
        assert path in body
    assert "requests.get" in body  # python example
    assert "fetch(" in body  # javascript example
    assert "curl" in body
    # swagger must NOT be mounted at /docs anymore: this page is our own HTML
    assert "swagger-ui" not in body.lower()


def test_swagger_ui_at_swagger(client) -> None:
    response = client.get("/swagger")
    assert response.status_code == 200
    assert "swagger" in response.text.lower()


def test_redoc_available(client) -> None:
    response = client.get("/redoc")
    assert response.status_code == 200
    assert "redoc" in response.text.lower()


def test_openapi_json_works(client) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    spec = response.json()
    assert spec["info"]["title"] == "Telegram Username Intelligence API"
    assert "/api/v1/check" in spec["paths"]


def test_static_assets_served(client) -> None:
    response = client.get("/static/site.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert ":root" in response.text
    assert "--accent" in response.text

    response = client.get("/static/tester.js")
    assert response.status_code == 200
    assert "BULK_MAX" in response.text


def test_footer_links_present(client) -> None:
    body = client.get("/").text
    assert "TG Username API" in body
    assert "t.me/yorifederation" in body  # Yori Federation replaces GitHub
    assert "github.com/harshi79/tg-username-api" not in body  # no GitHub promotion
    assert "/api/health" in body
    assert "/docs" in body
    assert "/swagger" in body
