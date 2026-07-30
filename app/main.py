"""FastAPI application: public website, API routes, docs, security.

Website (developer product pages)
---------------------------------
GET  /                       — landing page (dark graphite + emerald UI)
GET  /tester                 — interactive API playground
GET  /docs                   — custom documentation (this project's own)
GET  /swagger                — FastAPI Swagger UI (auto-generated)
GET  /redoc                  — ReDoc (auto-generated)
GET  /openapi.json           — OpenAPI schema
GET  /static/*               — website assets

Public API (versioned, rate limited: 25 requests/IP/minute)
-----------------------------------------------------------
GET  /api/health             — liveness probe
GET  /api/v1/check           — single username check
GET  /api/v1/report          — detailed single username report
POST /api/v1/check/bulk      — bulk check (max 15 usernames, bounded)

Security hooks (environment driven): API keys via ``API_KEYS`` (off by
default); rate limiting is ON by default for ``/api/*`` — see app/ratelimit.py.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .checker import UsernameChecker
from .config import settings
from .http import close_http_manager, get_http_manager
from .models import (
    BulkRequest,
    BulkResponse,
    CheckResponse,
    ErrorCode,
    ErrorInfo,
    ErrorResponse,
    HealthResponse,
    ReportResponse,
    utc_now_iso,
)
from .ratelimit import limiter
from .web import STATIC_DIR, render_page

logging.basicConfig(level=getattr(logging, "INFO"))
logger = logging.getLogger("tg_username_api")


# ---------------------------------------------------------------------------
# lifespan: own one pooled HTTP manager per instance
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.checker = UsernameChecker(get_http_manager())
    logger.info("telegram-username-api %s started (env=%s)", __version__, settings.app_env)
    try:
        yield
    finally:
        await close_http_manager()


app = FastAPI(
    title="Telegram Username Intelligence API",
    version=__version__,
    summary="Public-presence intelligence for Telegram usernames (t.me + Fragment).",
    description=(
        "Checks whether a Telegram username publicly resolves on Telegram and, when it does not, "
        "whether it exists as a collectible on Fragment. The API is **conservative by design**: a "
        "username is reported `available` only when every public source agrees; ambiguous or failed "
        "checks always return `unknown`. No Telegram account, bot token, wallet or Fragment login is "
        "required — only public web pages are read.\n\n"
        "Rate limits: 25 requests per IP per minute on `/api/*` (bulk: max 15 usernames). "
        "Custom documentation lives at `/docs`; this Swagger UI lives at `/swagger`."
    ),
    lifespan=lifespan,
    docs_url="/swagger",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)


# ---------------------------------------------------------------------------
# optional API key authentication
# ---------------------------------------------------------------------------


async def require_api_key(request: Request) -> None:
    """Enforce API keys only when ``API_KEYS`` is configured (fail-open by design)."""
    if not settings.auth_enabled:
        return
    provided = request.headers.get(settings.api_key_header, "")
    if provided not in settings.api_keys:
        # Never echo the provided key back.
        raise _http_error(401, ErrorCode.UNAUTHORIZED, "missing or invalid API key")


class _ApiHttpError(Exception):
    def __init__(self, status_code: int, error: ErrorInfo) -> None:
        self.status_code = status_code
        self.error = error


def _http_error(status_code: int, code: ErrorCode, message: str) -> _ApiHttpError:
    return _ApiHttpError(status_code, ErrorInfo(code=code, message=message))


# ---------------------------------------------------------------------------
# public API rate limiting (25 req/IP/min on /api/*, website exempt)
# ---------------------------------------------------------------------------


@app.middleware("http")
async def api_rate_limit(request: Request, call_next):
    path = request.url.path
    if not limiter.enabled or not limiter.applies_to(path):
        return await call_next(request)

    outcome = limiter.check(request)
    if not outcome.allowed:
        return JSONResponse(
            status_code=429,
            content=ErrorResponse(
                error=ErrorInfo(code=ErrorCode.RATE_LIMIT_EXCEEDED, message="Rate limit exceeded. Try again shortly.")
            ).model_dump(mode="json"),
            headers={"Retry-After": str(outcome.retry_after), **limiter.headers(outcome)},
        )

    response = await call_next(request)
    for name, value in limiter.headers(outcome).items():
        response.headers[name] = value
    return response


# ---------------------------------------------------------------------------
# structured error handlers — errors never surface as availability answers
# ---------------------------------------------------------------------------


@app.exception_handler(_ApiHttpError)
async def api_http_error_handler(_request: Request, exc: _ApiHttpError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=ErrorResponse(error=exc.error).model_dump(mode="json"))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorInfo(code=ErrorCode.VALIDATION_ERROR, message="request validation failed", source="api", retryable=False),
        ).model_dump(mode="json") | {"detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorInfo(code=ErrorCode.INTERNAL_ERROR, message="internal server error", source="api", retryable=True),
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def get_checker(request: Request) -> UsernameChecker:
    return request.app.state.checker


USERNAME_QUERY = Query(
    ...,
    min_length=1,
    max_length=256,
    description="Username in any accepted format: `durov`, `@durov`, `https://t.me/durov`.",
    examples=["durov", "@durov", "https://t.me/durov"],
)


# ---------------------------------------------------------------------------
# website routes (excluded from the OpenAPI schema; not rate limited)
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def website_home() -> HTMLResponse:
    return HTMLResponse(render_page("home", "TG Username API — Telegram usernames. One API.", "home"))


@app.get("/tester", response_class=HTMLResponse, include_in_schema=False)
async def website_tester() -> HTMLResponse:
    return HTMLResponse(render_page("tester", "API Tester — TG Username API", "tester"))


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def website_docs() -> HTMLResponse:
    return HTMLResponse(render_page("docs", "Documentation — TG Username API", "docs"))


# ---------------------------------------------------------------------------
# public API routes
# ---------------------------------------------------------------------------


@app.get(
    "/api/health",
    response_model=HealthResponse,
    tags=["meta"],
    summary="Liveness probe",
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get(
    "/api/v1/check",
    response_model=CheckResponse,
    tags=["checks"],
    summary="Check a single Telegram username",
    description=(
        "Normalizes and validates the input, checks the public Telegram page, and — only when the "
        "handle does not resolve — checks the public Fragment listing. Results are cached briefly "
        f"({settings.cache_ttl_seconds}s) because ownership state can change."
    ),
)
async def check_username(
    request: Request,
    username: str = USERNAME_QUERY,
    _auth: None = Depends(require_api_key),
) -> CheckResponse:
    return await get_checker(request).check_username(username)


@app.get(
    "/api/v1/report",
    response_model=ReportResponse,
    tags=["checks"],
    summary="Detailed report for a single username",
    description=(
        "Everything `/api/v1/check` returns, plus objective username characteristics "
        "(length, digits, underscores, repetition) and a clearly-labelled *heuristic* "
        "desirability score. The heuristic is **not** a market valuation."
    ),
)
async def report_username(
    request: Request,
    username: str = USERNAME_QUERY,
    _auth: None = Depends(require_api_key),
) -> ReportResponse:
    return await get_checker(request).report_username(username)


@app.post(
    "/api/v1/check/bulk",
    response_model=BulkResponse,
    tags=["checks"],
    summary="Check several usernames concurrently",
    description=(
        f"Accepts up to **{settings.bulk_max_usernames}** usernames per request (enforced "
        "server-side). Checks run concurrently with bounded concurrency towards Telegram and "
        "Fragment — the API never fires hundreds of simultaneous upstream requests. Input order "
        "is preserved; duplicates share a single upstream lookup."
    ),
)
async def check_bulk(
    payload: BulkRequest,
    request: Request,
    _auth: None = Depends(require_api_key),
) -> BulkResponse:
    if len(payload.usernames) > settings.bulk_max_usernames:
        raise _http_error(
            400,
            ErrorCode.PAYLOAD_TOO_LARGE,
            f"too many usernames: {len(payload.usernames)} provided, maximum is {settings.bulk_max_usernames} per request",
        )
    return await get_checker(request).check_bulk(payload)


# Static assets for the website (mounted last; explicit routes win).
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Keep the module import-time side-effect free for serverless reuse.
__all__ = ["app", "utc_now_iso"]
