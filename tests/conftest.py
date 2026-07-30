"""pytest plumbing: fake upstream transport + shared fixtures.

No real network access happens in tests: ``FakeHttpManager`` returns canned
:class:`app.http.UpstreamResponse` objects for t.me / fragment.com URLs and
raises for anything unexpected, which also proves the adapters never fire
surprise requests.
"""

from __future__ import annotations

import os
import sys
from typing import Callable

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.http import UpstreamResponse  # noqa: E402
from tests.pages import (  # noqa: E402
    FRAG_AVAILABLE_HTML,
    FRAG_AUCTION_HTML,
    FRAG_FOR_SALE_HTML,
    FRAG_GARBAGE_HTML,
    FRAG_PAGE_WITHOUT_BADGE_HTML,
    FRAG_SEARCH_EMPTY_HTML,
    FRAG_TAKEN_HTML,
    TELE_BARE_HTML,
    TELE_BARE_SUPPORT_HTML,
    TELE_BOT_HTML,
    TELE_CHANNEL_HTML,
    TELE_GARBAGE_HTML,
    TELE_GROUP_HTML,
    TELEGRAM_ORG_HTML,
)


def _page(status: int, final_url: str, body: str) -> UpstreamResponse:
    return UpstreamResponse(ok=True, status_code=status, final_url=final_url, text=body)


class FakeHttpManager:
    """Route-keyed fake of app.http.HttpManager."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._telegram: dict[str, Callable[[str], UpstreamResponse]] = {}
        self._fragment: dict[str, Callable[[str], UpstreamResponse]] = {}

    # -- scenario registration ------------------------------------------------
    def on_telegram(self, username: str, handler: Callable[[str], UpstreamResponse]) -> None:
        self._telegram[username.lower()] = handler

    def on_fragment(self, username: str, handler: Callable[[str], UpstreamResponse]) -> None:
        self._fragment[username.lower()] = handler

    # -- canned scenarios ------------------------------------------------------
    def telegram_page(self, username: str, body: str, status: int = 200) -> Callable[[str], UpstreamResponse]:
        return lambda url: _page(status, f"https://t.me/{username}", body)

    def telegram_redirect_org(self) -> Callable[[str], UpstreamResponse]:
        return lambda url: _page(200, "https://telegram.org/", TELEGRAM_ORG_HTML)

    def telegram_deep_link(self, username: str) -> Callable[[str], UpstreamResponse]:
        return lambda url: UpstreamResponse(
            ok=True,
            status_code=302,
            final_url=f"https://t.me/{username}",
            non_http_redirect=f"tg://resolve?domain={username}",
        )

    def telegram_timeout(self) -> Callable[[str], UpstreamResponse]:
        return lambda url: UpstreamResponse(ok=False, error_kind="timeout", error_detail="timeout after 8.0s")

    def telegram_429(self) -> Callable[[str], UpstreamResponse]:
        return lambda url: UpstreamResponse(ok=False, error_kind="rate_limited", status_code=429, error_detail="HTTP 429")

    def fragment_page(self, username: str, body: str, status: int = 200) -> Callable[[str], UpstreamResponse]:
        return lambda url: _page(status, f"https://fragment.com/username/{username}", body)

    def fragment_not_found(self, username: str) -> Callable[[str], UpstreamResponse]:
        return lambda url: _page(200, f"https://fragment.com/?query={username}", FRAG_SEARCH_EMPTY_HTML)

    def fragment_timeout(self) -> Callable[[str], UpstreamResponse]:
        return lambda url: UpstreamResponse(ok=False, error_kind="timeout", error_detail="timeout after 8.0s")

    # -- interface used by the adapters ----------------------------------------
    async def fetch(self, url: str) -> UpstreamResponse:
        self.calls.append(url)
        if url.startswith("https://t.me/"):
            username = url.rsplit("/", 1)[-1].lower()
            handler = self._telegram.get(username)
            if handler is None:
                raise AssertionError(f"unexpected telegram request for @{username}")
            return handler(url)
        if url.startswith("https://fragment.com/username/"):
            username = url.rsplit("/", 1)[-1].lower()
            handler = self._fragment.get(username)
            if handler is None:
                raise AssertionError(f"unexpected fragment request for @{username}")
            return handler(url)
        raise AssertionError(f"unexpected request to {url}")


@pytest.fixture()
def fake_http() -> FakeHttpManager:
    http = FakeHttpManager()

    # --- observed live behaviours (2026-07) -----------------------------------
    http.on_telegram("durov", http.telegram_page("durov", TELE_CHANNEL_HTML))
    http.on_telegram("durovschat", http.telegram_page("durovschat", TELE_GROUP_HTML))
    http.on_telegram("botfather", http.telegram_page("botfather", TELE_BOT_HTML))
    http.on_telegram("wqxjvkzq", http.telegram_page("wqxjvkzq", TELE_BARE_HTML))
    http.on_telegram("support", http.telegram_page("support", TELE_BARE_SUPPORT_HTML))
    http.on_telegram("firexi", http.telegram_deep_link("firexi"))
    http.on_telegram("gone404", lambda url: _page(404, "https://t.me/gone404", TELE_BARE_HTML.replace("wqxjvkzq", "gone404")))
    http.on_telegram("orgname", http.telegram_redirect_org())
    http.on_telegram("flakyuser", http.telegram_timeout())
    http.on_telegram("busyuser", http.telegram_429())
    http.on_telegram("oddpage", http.telegram_page("oddpage", TELE_GARBAGE_HTML))

    http.on_fragment("durov", http.fragment_page("durov", FRAG_TAKEN_HTML))
    http.on_fragment("support", http.fragment_not_found("support"))
    http.on_fragment("wqxjvkzq", http.fragment_not_found("wqxjvkzq"))
    http.on_fragment("polymarket", http.fragment_page("polymarket", FRAG_AUCTION_HTML))
    http.on_fragment("scalp", http.fragment_page("scalp", FRAG_FOR_SALE_HTML))
    http.on_fragment("stormed", http.fragment_page("stormed", FRAG_AVAILABLE_HTML))
    http.on_fragment("oddname", http.fragment_page("oddname", FRAG_PAGE_WITHOUT_BADGE_HTML))
    http.on_fragment("gone404", http.fragment_not_found("gone404"))
    http.on_fragment("orgname", http.fragment_not_found("orgname"))
    http.on_fragment("walled", http.fragment_page("walled", FRAG_GARBAGE_HTML))
    http.on_fragment("flakyser", http.fragment_timeout())
    http.on_fragment("flakyuser", http.fragment_not_found("flakyuser"))
    http.on_fragment("busyuser", http.fragment_not_found("busyuser"))

    # names from the task's bulk example: clearly unclaimed (404 + no fragment page)
    for name in ("yorivex", "yorixa", "yorzen"):
        http.on_telegram(name, lambda url, n=name: _page(404, f"https://t.me/{n}", TELE_BARE_HTML.replace("wqxjvkzq", n)))
        http.on_fragment(name, getattr(http, "fragment_not_found")(name))

    return http


@pytest.fixture()
def checker(fake_http: FakeHttpManager):
    from app.checker import UsernameChecker

    return UsernameChecker(fake_http)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Isolate every test from the (default-on) in-memory API rate limiter."""
    from app.ratelimit import limiter

    backend = limiter.backend
    if hasattr(backend, "clear"):
        backend.clear()
    yield
    if hasattr(backend, "clear"):
        backend.clear()
