"""Application configuration.

All configurable values are read from environment variables so the project can
be deployed on Vercel (or any other platform) without code changes. Sensible
defaults are provided for local development. No secrets are required for the
core public checks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int_env(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _float_env(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings (frozen at import time; safe for serverless reuse)."""

    # --- Upstream endpoints ------------------------------------------------
    telegram_base_url: str = field(default_factory=lambda: os.getenv("TELEGRAM_BASE_URL", "https://t.me").rstrip("/"))
    fragment_base_url: str = field(default_factory=lambda: os.getenv("FRAGMENT_BASE_URL", "https://fragment.com").rstrip("/"))
    user_agent: str = field(
        default_factory=lambda: os.getenv(
            "HTTP_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64; rv:127.0) Gecko/20100101 Firefox/127.0",
        )
    )

    # --- HTTP behaviour -----------------------------------------------------
    http_timeout_seconds: float = field(default_factory=lambda: _float_env("HTTP_TIMEOUT_SECONDS", 8.0, 1.0, 30.0))
    http_max_attempts: int = field(default_factory=lambda: _int_env("HTTP_MAX_ATTEMPTS", 3, 1, 5))
    http_backoff_base_seconds: float = field(default_factory=lambda: _float_env("HTTP_BACKOFF_BASE_SECONDS", 0.4, 0.0, 5.0))
    max_redirects: int = field(default_factory=lambda: _int_env("HTTP_MAX_REDIRECTS", 5, 0, 10))
    retry_after_cap_seconds: float = field(default_factory=lambda: _float_env("RETRY_AFTER_CAP_SECONDS", 4.0, 0.0, 30.0))

    # --- Bounded concurrency ------------------------------------------------
    telegram_concurrency: int = field(default_factory=lambda: _int_env("TELEGRAM_CONCURRENCY", 4, 1, 20))
    fragment_concurrency: int = field(default_factory=lambda: _int_env("FRAGMENT_CONCURRENCY", 2, 1, 10))
    bulk_concurrency: int = field(default_factory=lambda: _int_env("BULK_CONCURRENCY", 5, 1, 25))

    # --- Bulk limits ---------------------------------------------------------
    # Hard maximum of usernames per bulk request (public API contract).
    bulk_max_usernames: int = 15

    # --- Cache ----------------------------------------------------------------
    cache_ttl_seconds: int = field(default_factory=lambda: _int_env("CACHE_TTL_SECONDS", 300, 0, 86400))
    cache_max_entries: int = field(default_factory=lambda: _int_env("CACHE_MAX_ENTRIES", 2048, 16, 100000))

    # --- Optional API security ------------------------------------------------
    # Comma separated list of accepted API keys. Empty = authentication disabled.
    api_keys: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            k.strip() for k in os.getenv("API_KEYS", "").split(",") if k.strip()
        )
    )
    api_key_header: str = field(default_factory=lambda: os.getenv("API_KEY_HEADER", "X-API-Key"))

    # --- Public API rate limiting ---------------------------------------------
    # Production default: 25 requests per client IP per fixed 60-second window,
    # applied to /api/* routes only (website pages and static assets are exempt).
    # In-memory = best-effort per serverless instance; see app/ratelimit.py.
    rate_limit_enabled: bool = field(default_factory=lambda: _bool_env("RATE_LIMIT_ENABLED", True))
    rate_limit_requests_per_minute: int = field(
        default_factory=lambda: _int_env("RATE_LIMIT_REQUESTS_PER_MINUTE", 25, 1, 100000)
    )
    rate_limit_window_seconds: int = field(
        default_factory=lambda: _int_env("RATE_LIMIT_WINDOW_SECONDS", 60, 5, 3600)
    )
    # When to trust proxy forwarding headers for the client IP:
    #   "auto"  -> only inside the Vercel runtime (VERCEL env var present)
    #   "true"  -> always (your own trusted reverse proxy terminates TLS)
    #   "false" -> never (direct/local deployments: use the socket peer IP)
    trust_proxy_headers: str = field(
        default_factory=lambda: os.getenv("TRUST_PROXY_HEADERS", "auto").strip().lower()
    )

    # --- Misc ------------------------------------------------------------------
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "production"))

    @property
    def auth_enabled(self) -> bool:
        return len(self.api_keys) > 0

    @property
    def on_vercel(self) -> bool:
        return bool(os.getenv("VERCEL"))

    @property
    def trust_proxy(self) -> bool:
        if self.trust_proxy_headers == "auto":
            return self.on_vercel
        return self.trust_proxy_headers in {"1", "true", "yes", "on"}


settings = Settings()
