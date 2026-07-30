"""Shared asynchronous HTTP layer.

Provides one pooled ``httpx.AsyncClient`` per application instance, bounded
per-host concurrency, manual redirect following (so non-HTTP schemes such as
``tg://`` can be observed instead of failing), limited retries with
exponential backoff and structured classification of network failures.

A network failure is *always* surfaced as an error and never mistaken for a
semantic answer (e.g. "username available").
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from .config import settings

logger = logging.getLogger(__name__)


@dataclass
class UpstreamResponse:
    """Transport-level result of an upstream lookup."""

    ok: bool
    status_code: int | None = None
    final_url: str | None = None          # URL of the last response (after manual redirects)
    redirect_chain: list[str] = field(default_factory=list)
    non_http_redirect: str | None = None  # e.g. "tg://resolve?domain=..." when Telegram redirects off-HTTP
    text: str = ""                        # response body (may be empty)
    headers: dict[str, str] = field(default_factory=dict)
    error_kind: str | None = None         # timeout | network | rate_limited | server_error | http_status
    error_detail: str | None = None
    attempts: int = 0


class HttpManager:
    """Owns the pooled client and per-host semaphores."""

    def __init__(self) -> None:
        limits = httpx.Limits(max_connections=50, max_keepalive_connections=20, keepalive_expiry=60.0)
        timeout = httpx.Timeout(settings.http_timeout_seconds, connect=min(5.0, settings.http_timeout_seconds))
        self._client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=False,  # redirects are followed manually to observe non-HTTP targets
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            },
        )
        self._semaphores: dict[str, asyncio.Semaphore] = {
            "t.me": asyncio.Semaphore(settings.telegram_concurrency),
            "fragment.com": asyncio.Semaphore(settings.fragment_concurrency),
        }

    async def aclose(self) -> None:
        await self._client.aclose()

    def _semaphore_for(self, url: str) -> asyncio.Semaphore:
        host = (urlparse(url).hostname or "").lower()
        return self._semaphores.get(host, asyncio.Semaphore(max(settings.fragment_concurrency, 2)))

    async def fetch(self, url: str) -> UpstreamResponse:
        """GET ``url`` with bounded concurrency, retries and manual redirects."""

        semaphore = self._semaphore_for(url)
        async with semaphore:
            return await self._fetch_with_retries(url)

    async def _fetch_with_retries(self, url: str) -> UpstreamResponse:
        attempts = 0
        last: UpstreamResponse | None = None
        while attempts < settings.http_max_attempts:
            attempts += 1
            result = await self._single_attempt(url)
            result.attempts = attempts
            if result.ok or result.error_kind == "http_status":
                # 4xx other than 429 => definitive answer, no retry.
                if result.status_code == 429 or (result.status_code is not None and result.status_code >= 500):
                    last = result
                else:
                    return result
            elif result.error_kind in {"timeout", "network"} or result.error_kind == "rate_limited":
                last = result
            else:
                return result

            if attempts < settings.http_max_attempts:
                delay = settings.http_backoff_base_seconds * (2 ** (attempts - 1))
                # Honor Retry-After (capped) when the upstream asks for it.
                retry_after = last.headers.get("retry-after") if last.headers else None
                if retry_after:
                    try:
                        delay = max(delay, min(float(retry_after), settings.retry_after_cap_seconds))
                    except ValueError:
                        pass
                delay += random.uniform(0, 0.2)
                logger.debug("retrying %s in %.2fs (attempt %d failed: %s)", url, delay, attempts, last.error_kind if last else "?")
                await asyncio.sleep(delay)

        return last if last is not None else UpstreamResponse(ok=False, error_kind="network", error_detail="no attempts executed")

    async def _single_attempt(self, url: str) -> UpstreamResponse:
        redirect_chain: list[str] = []
        current = url
        try:
            for _hop in range(settings.max_redirects + 1):
                response = await self._client.get(current)
                if response.is_redirect:
                    location = response.headers.get("location", "")
                    redirect_chain.append(location)
                    absolute = urljoin(current, location)
                    scheme = urlparse(absolute).scheme.lower()
                    if scheme in {"http", "https"}:
                        current = absolute
                        continue
                    # Non-HTTP redirect target (e.g. tg://...) — stop and report.
                    return UpstreamResponse(
                        ok=True,
                        status_code=response.status_code,
                        final_url=current,
                        redirect_chain=redirect_chain,
                        non_http_redirect=absolute,
                        text=response.text or "",
                        headers=dict(response.headers),
                    )
                return self._wrap(current, redirect_chain, response)
            return UpstreamResponse(
                ok=False,
                error_kind="http_status",
                error_detail=f"too many redirects (>{settings.max_redirects})",
                redirect_chain=redirect_chain,
                final_url=current,
            )
        except httpx.TimeoutException as exc:
            return UpstreamResponse(ok=False, error_kind="timeout", error_detail=f"timeout after {settings.http_timeout_seconds}s: {exc.__class__.__name__}", redirect_chain=redirect_chain)
        except httpx.TransportError as exc:
            return UpstreamResponse(ok=False, error_kind="network", error_detail=f"transport error: {exc.__class__.__name__}: {exc}", redirect_chain=redirect_chain)
        except Exception as exc:  # defensive: never leak an unexpected crash as "ok"
            return UpstreamResponse(ok=False, error_kind="network", error_detail=f"unexpected client error: {exc.__class__.__name__}", redirect_chain=redirect_chain)

    @staticmethod
    def _wrap(url: str, chain: list[str], response: httpx.Response) -> UpstreamResponse:
        error_kind = None
        if response.status_code == 429:
            error_kind = "rate_limited"
        elif response.status_code >= 500:
            error_kind = "server_error"
        elif response.status_code >= 400:
            error_kind = None  # 404 etc. are informative answers, not transport errors
        ok = response.status_code < 500 and response.status_code != 429
        # Guard against absurdly large bodies
        body = response.text or ""
        if len(body) > 2_000_000:
            body = body[:2_000_000]
        return UpstreamResponse(
            ok=ok,
            status_code=response.status_code,
            final_url=url,
            redirect_chain=chain,
            text=body,
            headers=dict(response.headers),
            error_kind=error_kind,
            error_detail=None if ok else f"upstream returned HTTP {response.status_code}",
        )


# ---------------------------------------------------------------------------
# Application-scoped singleton
# ---------------------------------------------------------------------------

_manager: HttpManager | None = None


def get_http_manager() -> HttpManager:
    global _manager
    if _manager is None:
        _manager = HttpManager()
    return _manager


async def close_http_manager() -> None:
    global _manager
    if _manager is not None:
        await _manager.aclose()
        _manager = None
