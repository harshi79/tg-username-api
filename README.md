# TG Username API

Fast, conservative **Telegram username intelligence** built with **Python + FastAPI**, deployable
on **Vercel's Python runtime**. It checks whether a username publicly resolves on Telegram, and —
only when it does not — whether it exists as a collectible on [Fragment](https://fragment.com/),
including public marketplace state and TON prices.

> **Core reliability rule:** a username is reported `available` **only** when every public source
> provides a clean negative. Telegram *not resolving* never implies availability by itself.
> Ambiguity, network failures, rate limits, timeouts or anti-bot pages always degrade to `unknown`.

No Telegram account, phone number, API ID/hash, bot token, TON wallet, Fragment login, cookies or
any other private credentials are used — the API reads **public web pages only** and never bypasses
authentication, CAPTCHAs, rate limits or access controls.

## Product website

The deployment is a complete developer-facing product, not just bare endpoints:

| Route | What it is |
| --- | --- |
| `/` | Landing page — what the API does, status model, feature cards, live base URL, sample request/response |
| `/tester` | **API Tester** — interactive playground (single check, detailed report, bulk with live `N / 15 usernames` counter), raw JSON panels, keyboard friendly |
| `/docs` | **Documentation** — own polished docs: introduction, dynamic base URL, rate limits, statuses, every endpoint with cURL / JavaScript / Python examples and errors |
| `/swagger` | FastAPI Swagger UI (labelled “OpenAPI” in navigation) |
| `/redoc` | ReDoc |
| `/openapi.json` | Raw OpenAPI schema (API routes only — website pages are excluded) |
| `/static/*` | Website assets (dark graphite + emerald/teal theme, CSS variables) |

The API base URL shown on the site is derived from the **current host in the browser**
(`window.location.origin + /api/v1`) — no production domain is hardcoded anywhere.

Design: dark-first, deep graphite surfaces, restrained emerald/teal accent, subtle borders, polished
code blocks with Copy buttons, status badges, responsive mobile layout, reduced-motion friendly —
all driven by CSS variables in `app/web/static/site.css`.

## API endpoints

| Method | Path | Description |
| ------ | ---- | ----------- |
| GET | `/api/v1/check?username=durov` | Single username check |
| GET | `/api/v1/report?username=durov` | Detailed report (characteristics + heuristic) |
| POST | `/api/v1/check/bulk` | Bulk check — **max 15 usernames**, JSON `{"usernames": [...]}` |
| GET | `/api/health` | Liveness probe → `{"status":"ok"}` |

### Rate limits

* **25 requests per IP address per minute** (fixed one-minute windows), applied to `/api/*` routes
  only — website pages and static assets are exempt.
* Response headers on every API call: `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset` (unix epoch); `Retry-After` on 429s.
* One bulk HTTP request counts as **one** API request; per-username upstream effort is bounded
  server-side (bounded concurrency + deduplication).
* Exceeding the quota returns HTTP **429**:

```json
{
  "success": false,
  "error": { "code": "rate_limit_exceeded", "message": "Rate limit exceeded. Try again shortly." }
}
```

* **Serverless limitation:** the built-in limiter is in-memory, hence best-effort *per Vercel
  instance* (a fleet of N instances may each allow the quota). The storage layer is isolated behind
  the `RateLimitBackend` protocol in `app/ratelimit.py`, so a shared backend (e.g. Upstash Redis)
  can be plugged in later for globally strict enforcement — no dependencies are required today.
* Client IP: forwarding headers (`x-vercel-forwarded-for`, `x-real-ip`) are trusted **only** inside
  the Vercel runtime (or with `TRUST_PROXY_HEADERS=true`); otherwise the socket peer IP is used so
  the limiter cannot be bypassed by spoofing headers.

### Bulk limits

**Maximum 15 usernames per bulk request — enforced on the server** (HTTP 400
`payload_too_large` beyond that), independent of any frontend validation. The tester prevents
submission above 15 and explains the limit.

## Local installation

```bash
git clone <this repo>
cd tg-username-api
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Local development

```bash
uvicorn app.main:app --reload --port 8000
```

Then open:

* Website: <http://127.0.0.1:8000/>
* Tester: <http://127.0.0.1:8000/tester>
* Docs: <http://127.0.0.1:8000/docs>
* Swagger: <http://127.0.0.1:8000/swagger>

## Tests

```bash
pip install pytest pytest-asyncio
pytest -q
```

83 tests, including: homepage/tester/docs/swagger loading, OpenAPI schema correctness, the full
rate-limit contract (first 25 allowed, 26th → 429, headers, website routes exempt), bulk 15/16
boundaries, and the original adapter suite replaying the **live layouts recorded from t.me and
fragment.com on 2026-07-30** (no false `available`; malformed upstreams degrade to `unknown`;
invalid input never hits the network).

## Examples

`GET /api/v1/check?username=durov` (taken channel — fields exactly as returned):

```json
{
  "success": true,
  "username": "durov",
  "validation": { "valid": true, "input": "durov", "normalized": "durov", "reason": null },
  "telegram": {
    "checked": true, "exists": true, "entity_type": "channel",
    "page_kind": "rich_profile_page", "display_name": "Pavel Durov",
    "public_url": "https://t.me/durov", "http_status": 200,
    "final_url": "https://t.me/durov", "evidence": ["..."], "error": null
  },
  "fragment": {
    "checked": false, "found": null, "collectible": null, "status": null,
    "price": null, "auction": null, "url": null,
    "evidence": ["not queried: the username already resolves on Telegram"], "error": null
  },
  "result": { "status": "taken",
    "explanation": "@durov currently resolves on Telegram (public channel page)." },
  "cached": false,
  "checked_at": "2026-07-30T09:45:19Z"
}
```

`GET /api/v1/check?username=example` where the handle is not resolving but Fragment tracks it:

```json
{
  "success": true,
  "username": "example",
  "telegram": { "exists": false, "entity_type": null },
  "fragment": {
    "checked": true, "found": true, "collectible": true, "status": "for_sale",
    "price": { "amount": 250, "currency": "TON", "approx_usd": "$355.40" },
    "url": "https://fragment.com/username/example"
  },
  "result": { "status": "fragment_collectible" }
}
```

`GET /api/v1/report?username=durov` adds (heuristic is clearly labelled, **not** a valuation):

```json
{
  "characteristics": { "length": 5, "digit_count": 0, "underscore_count": 0, "only_letters": true, "..." : "..." },
  "heuristic_score": { "score": 74, "label": "heuristic", "factor_notes": ["minimum possible length (5) — short handles are scarce", "..."] },
  "signals": ["page title: 'Telegram: View @durov'", "..."]
}
```

`POST /api/v1/check/bulk`:

```json
{ "usernames": ["yorivex", "@yorixa", "https://t.me/yorzen"] }
```

```json
{ "success": true, "total": 3, "results": [ /* CheckResponse objects in input order */ ] }
```

## Project structure

```text
tg-username-api/
├── api/
│   └── index.py            # Vercel entrypoint (exposes the ASGI app)
├── app/
│   ├── main.py             # FastAPI app, website + API routes, rate limit middleware
│   ├── config.py           # environment-driven settings
│   ├── models.py           # Pydantic request/response models
│   ├── validators.py       # normalization + validation (no network)
│   ├── http.py             # pooled async HTTP, retries/backoff, per-host semaphores
│   ├── telegram.py         # Telegram (t.me) adapter — swap if Telegram changes
│   ├── fragment.py         # Fragment adapter — swap if Fragment changes
│   ├── checker.py          # orchestration + conservative decision matrix
│   ├── ratelimit.py        # 25 req/IP/min on /api/*, swappable backend protocol
│   ├── cache.py            # in-memory TTL cache
│   └── web/
│       ├── templates/      # base + home / tester / docs pages
│       └── static/         # site.css (theme), site.js, tester.js
├── tests/                  # 83 tests (adapters, API, website, rate limits)
├── requirements.txt
├── vercel.json
├── pytest.ini
├── .env.example
└── .gitignore
```

## Vercel deployment

Everything is **one Vercel project** — website, tester, docs, swagger and API deploy together:

```bash
npm i -g vercel
vercel          # from the repo root
vercel --prod
```

or import the repo in the Vercel dashboard (*New Project → Framework Preset: Other*). No build
command is needed; Vercel installs `requirements.txt` and serves `api/index.py` as a native ASGI
function (`vercel.json` rewrites all routes to it, capped at 30 s). Resulting surface:

`https://<domain>/` website · `/tester` tester · `/docs` docs · `/swagger` swagger ·
`/api/v1/...` API · `/api/health` health.

Constraints respected: no persistent DB, no background workers, no filesystem state, no
long-running processes, stateless cache/limiter.

## Environment variables

All optional — sane production defaults built in (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BASE_URL` / `FRAGMENT_BASE_URL` | `https://t.me` / `https://fragment.com` | Upstream bases (override for tests) |
| `HTTP_USER_AGENT` | Firefox UA string | UA for public page lookups |
| `HTTP_TIMEOUT_SECONDS` | `8` | Per-attempt upstream timeout |
| `HTTP_MAX_ATTEMPTS` / `HTTP_BACKOFF_BASE_SECONDS` | `3` / `0.4` | Retries with exponential backoff |
| `TELEGRAM_CONCURRENCY` / `FRAGMENT_CONCURRENCY` | `4` / `2` | Per-host request caps |
| `BULK_CONCURRENCY` | `5` | Parallel bulk items |
| `CACHE_TTL_SECONDS` / `CACHE_MAX_ENTRIES` | `300` / `2048` | Result cache (ownership changes!) |
| `API_KEYS` / `API_KEY_HEADER` | *(off)* / `X-API-Key` | Optional API-key auth on `/api/v1/*` |
| `RATE_LIMIT_ENABLED` | `true` | Public API rate limiting on `/api/*` |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `25` | Quota per IP per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Fixed window length |
| `TRUST_PROXY_HEADERS` | `auto` | Trust forwarding headers only on Vercel / trusted proxy |

Bulk size (15) is a fixed public contract, not an env tuneable. Credentials are only read from the
environment and never appear in responses, pages or logs.

## Status taxonomy

| Status | Meaning |
| --- | --- |
| `taken` | Currently resolves on Telegram (channel/group/bot page, or Fragment “claimed” report consistent with a bare user page). |
| `fragment_collectible` | Not publicly resolvable, but Fragment tracks it as a collectible (auction / for sale / sold / unavailable / auctionable). |
| `available` | Telegram **clearly** does not resolve (404 or telegram.org redirect) **and** Fragment has no page **and** no upstream failed. Can change anytime. |
| `invalid` | Failed local validation; no external request made. |
| `unknown` | **The API could not safely determine the state.** Inconclusive pages, upstream failure, rate limits, redesigns. Never assume availability. |

## Explanation of `unknown`

Public Telegram pages are deliberately minimal (verified live, 2026-07-30):

1. **Bare contact pages are ambiguous** — Telegram renders the identical
   *“If you have Telegram, you can contact @x right away”* page for a registered user with no public
   metadata (e.g. `@support`) **and** for an unclaimed random handle. Those return
   `exists: null / page_kind: bare_contact_page` and overall `unknown` — never a guess.
2. **Failure ≠ availability** — timeouts, TLS errors, 429s, 5xx, anti-bot pages and
   `tg://` deep-link redirects produce structured errors or `exists: null`, never `available`.
3. **Discordant signals stay discordant** — Telegram 404 + Fragment “claimed” ⇒ `unknown` with the
   conflict documented.
4. **`available` requires two clean negatives** (Telegram + Fragment) and a short cache TTL.
5. Reserved/frozen/formerly-owned handles and 4-char names may be publicly invisible → `unknown`.

## Known limitations

* **Users with no public metadata** may surface as `unknown` instead of `taken` (bare-page
  ambiguity) — the conservative trade-off required by the “no false availability” rule.
* **Fragment has no documented public API** — the adapter parses public pages; if Fragment
  redesigns, it degrades to `unknown` (never wrong answers). Isolated in `app/fragment.py`.
* **In-memory rate limiter & cache** are per serverless instance (see *Rate limits* above); a
  shared backend can be introduced via the `RateLimitBackend` protocol when needed.
* **Upstream throttling** still applies to heavy bulk usage; the API honours `Retry-After` and keeps
  request rates low by design.
* The **heuristic score** resembles rarity, not value — never present it as a market price.

## License

MIT — see [LICENSE](LICENSE).
