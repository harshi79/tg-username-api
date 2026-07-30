"""Public API rate limiting.

Production policy
-----------------
* Scope ......... every request whose path starts with ``/api/`` (website pages
                  and static assets are intentionally exempt).
* Limit ......... 25 requests per client IP per fixed 60-second window
                  (configurable via environment variables).
* Response ...... HTTP 429 with the structured body
                  ``{"success": false, "error": {"code": "rate_limit_exceeded", ...}}``
                  plus ``Retry-After`` and ``X-RateLimit-*`` headers. Successful
                  responses also carry the ``X-RateLimit-*`` headers.

Client IP
---------
Forwarding headers are only trusted when running behind a proxy that is known
to set them authoritatively:

* ``TRUST_PROXY_HEADERS=auto`` (default) trusts ``x-vercel-forwarded-for`` /
  ``x-real-ip`` only inside the Vercel runtime (``VERCEL`` env var present),
  where the platform overwrites these headers with the real connecting IP.
* Outside a trusted proxy the socket peer IP (``request.client.host``) is used
  and arbitrary client-supplied forwarding headers are ignored, so the limiter
  cannot be trivially bypassed by spoofing.

Backend
-------
The default backend is an in-memory fixed-window counter. On serverless
platforms this is **best-effort per instance**: a fleet of N instances can each
allow the full quota. The storage layer is deliberately isolated behind the
``RateLimitBackend`` protocol so a shared backend (e.g. Upstash Redis) can be
dropped in later without touching the policy code — the project stays
dependency-free until then.
"""

from __future__ import annotations

import time
from typing import Protocol
from dataclasses import dataclass

from fastapi import Request

from .config import settings


# ---------------------------------------------------------------------------
# client identity
# ---------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    """Best available client IP, only trusting proxy headers when appropriate."""
    if settings.trust_proxy:
        # Vercel (and similar platforms) overwrite these at the edge.
        vff = request.headers.get("x-vercel-forwarded-for")
        if vff:
            return vff.split(",", 1)[0].strip() or "unknown"
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip() or "unknown"
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",", 1)[0].strip() or "unknown"
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# backend protocol + in-memory implementation
# ---------------------------------------------------------------------------


@dataclass
class RateLimitOutcome:
    allowed: bool
    limit: int
    remaining: int
    reset_epoch: int          # unix epoch when the current window closes
    retry_after: int          # seconds the client should wait when blocked


class RateLimitBackend(Protocol):
    """Storage contract. Swap implementations to get a globally strict limiter."""

    def hit(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> RateLimitOutcome:
        ...


class InMemoryRateLimitBackend:
    """Fixed-window in-memory counters (per process / per serverless instance)."""

    _MAX_KEYS = 10_000

    def __init__(self) -> None:
        # key -> (window_start_epoch, count)
        self._counters: dict[str, tuple[int, int]] = {}

    def hit(self, key: str, limit: int, window_seconds: int, now: float | None = None) -> RateLimitOutcome:
        now = time.time() if now is None else now
        window_start = int(now // window_seconds) * window_seconds
        reset_epoch = window_start + window_seconds
        retry_after = max(1, int(reset_epoch - now))

        stored_window, count = self._counters.get(key, (window_start, 0))
        if stored_window != window_start:
            count = 0  # new window

        outcome = RateLimitOutcome(
            allowed=count < limit,
            limit=limit,
            remaining=max(0, limit - count - 1) if count < limit else 0,
            reset_epoch=reset_epoch,
            retry_after=retry_after,
        )
        if outcome.allowed:
            self._counters[key] = (window_start, count + 1)
        else:
            self._counters[key] = (window_start, count)

        if len(self._counters) > self._MAX_KEYS:
            self._purge(window_start)
        return outcome

    def _purge(self, current_window: int) -> None:
        stale = [k for k, (w, _c) in self._counters.items() if w < current_window]
        for k in stale:
            self._counters.pop(k, None)

    def clear(self) -> None:
        self._counters.clear()


# ---------------------------------------------------------------------------
# limiter facade
# ---------------------------------------------------------------------------


class RateLimiter:
    """Policy layer: decides scope and produces outcomes. Backend-swappable."""

    def __init__(self, backend: RateLimitBackend | None = None) -> None:
        self.backend: RateLimitBackend = backend or InMemoryRateLimitBackend()

    @property
    def enabled(self) -> bool:
        return settings.rate_limit_enabled

    def applies_to(self, path: str) -> bool:
        # Only the public API. Website pages (/ , /tester, /docs, /swagger,
        # /redoc, /openapi.json) and static assets are exempt by design.
        return path.startswith("/api/")

    def check(self, request: Request) -> RateLimitOutcome:
        key = f"ip:{client_ip(request)}"
        return self.backend.hit(
            key,
            limit=settings.rate_limit_requests_per_minute,
            window_seconds=settings.rate_limit_window_seconds,
        )

    @staticmethod
    def headers(outcome: RateLimitOutcome) -> dict[str, str]:
        return {
            "X-RateLimit-Limit": str(outcome.limit),
            "X-RateLimit-Remaining": str(outcome.remaining),
            "X-RateLimit-Reset": str(outcome.reset_epoch),
        }


# Application-scoped limiter (instance-local, like the result cache).
limiter = RateLimiter()
