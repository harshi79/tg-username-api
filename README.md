# Telegram Username Intelligence API

Fast, conservative **Telegram username intelligence** built with **Python + FastAPI**, designed to run
on **Vercel's Python runtime**. It checks whether a username publicly resolves on Telegram, and — only
when it does not — whether it exists as a collectible on [Fragment](https://fragment.com/).

> **Core reliability rule:** a username is reported `available` **only** when every public source
> provides a clean negative. Telegram *not resolving* never implies availability by itself.
> Ambiguity, network failures, rate limits, timeouts or anti-bot pages always degrade to `unknown`.

No Telegram account, phone number, API ID/hash, bot token, TON wallet, Fragment login, cookies or any
other private credentials are used — the API reads **public web pages only** and never bypasses
authentication, CAPTCHAs, rate limits or access controls.

## Features

- **Input normalization** — `durov`, `@durov`, `t.me/durov`, `https://t.me/durov`, `tg://resolve?domain=durov`
  all normalize to `durov`.
- **Pre-flight validation** — obviously invalid input never triggers an external request.
- **Telegram public check** — detects channel / group / bot pages and bare user pages, handles
  redirects (including `telegram.org` and `tg://` targets), 404s, 429s, 5xx, timeouts and garbage
  responses. Never fabricates profile information.
- **Fragment public check (separate adapter)** — reads the public `fragment.com/username/<u>` page
  state (`Taken`, `On auction`, `For sale`, `Available`, `Sold`, `Unavailable`), the publicly
  displayed TON price (column-aligned from Fragment's own labelled tables — never estimated) and the
  public Fragment URL. Easily updatable if Fragment changes its site.
- **Combined, conservative verdict** — `taken`, `fragment_collectible`, `available`, `invalid`,
  `unknown`.
- **Bulk checking** with bounded concurrency, per-upstream concurrency limits and in-flight
  deduplication.
- **Performance** — async `httpx` with connection pooling, timeouts, exponential-backoff retries
  (honouring capped `Retry-After`), per-host request semaphores and a short in-memory TTL cache.
- **Structured errors** — distinguish invalid input, upstream timeout/rate-limit/server errors,
  unrecognized upstream responses, blocked requests and internal errors. Upstream errors are never
  converted into `available`.
- **Optional security hooks** — API-key auth and a per-client rate limiter, enabled purely via
  environment variables. Disabled by default; secrets are never logged or exposed.
- **OpenAPI/Swagger docs** out of the box (`/docs`).

## Project structure

```text
tg-username-api/
├── api/
│   └── index.py          # Vercel entrypoint (exposes the ASGI app)
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI app, routes, error handlers, optional security
│   ├── config.py         # environment-driven settings
│   ├── models.py         # Pydantic request/response models
│   ├── validators.py     # normalization + validation (no network)
│   ├── http.py           # pooled async HTTP, retries/backoff, per-host semaphores
│   ├── telegram.py       # Telegram (t.me) adapter  — swap if Telegram changes
│   ├── fragment.py       # Fragment adapter          — swap if Fragment changes
│   ├── checker.py        # orchestration + conservative decision matrix
│   └── cache.py          # in-memory TTL cache
├── tests/                # pytest suite (fake upstreams replaying observed live pages)
├── requirements.txt
├── vercel.json
├── pytest.ini
├── .env.example
└── .gitignore
```

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

Then open <http://127.0.0.1:8000/docs> for the interactive Swagger UI.

## Tests

```bash
pip install pytest pytest-asyncio
pytest -q
```

The suite replays the **actual live layouts recorded from t.me and fragment.com on 2026-07-30** and
asserts the safety properties (no false `available`; malformed upstream responses degrade to
`unknown`; invalid input never hits the network; bulk deduplication; error taxonomy).

## API endpoints

| Method | Path                  | Description                                  |
| ------ | --------------------- | -------------------------------------------- |
| GET    | `/`                   | API information and endpoint directory       |
| GET    | `/api/health`         | Liveness probe → `{"status":"ok"}`           |
| GET    | `/api/v1/check`       | Single username check (`?username=...`)      |
| GET    | `/api/v1/report`      | Detailed report (characteristics + heuristic)|
| POST   | `/api/v1/check/bulk`  | Bulk check, JSON body `{"usernames": [...]}` |

### `GET /api/v1/check?username=durov`

```json
{
  "success": true,
  "username": "durov",
  "validation": { "valid": true, "input": "durov", "normalized": "durov", "reason": null },
  "telegram": {
    "checked": true,
    "exists": true,
    "entity_type": "channel",
    "page_kind": "rich_profile_page",
    "display_name": "Pavel Durov",
    "public_url": "https://t.me/durov",
    "http_status": 200,
    "evidence": ["page title: 'Telegram: View @durov'", "public counters: 11 419 432  subscribers", "..."],
    "error": null
  },
  "fragment": { "checked": false, "found": null, "...": "not queried: username resolves on Telegram" },
  "result": { "status": "taken", "explanation": "@durov currently resolves on Telegram (public channel page)." },
  "cached": false,
  "checked_at": "2026-07-30T09:45:19Z"
}
```

Username on Fragment (Telegram not publicly resolvable):

```json
{
  "success": true,
  "username": "example",
  "telegram": { "exists": false, "entity_type": null },
  "fragment": {
    "checked": true,
    "found": true,
    "collectible": true,
    "status": "for_sale",
    "price": { "amount": 250, "currency": "TON", "approx_usd": "$355.40" },
    "url": "https://fragment.com/username/example"
  },
  "result": { "status": "fragment_collectible" }
}
```

### `GET /api/v1/report?username=durov`

Everything `/check` returns, plus:

```json
{
  "characteristics": {
    "length": 5, "digit_count": 0, "underscore_count": 0, "alpha_count": 5,
    "starts_with_letter": true, "ends_with_letter_or_digit": true,
    "has_digits": false, "has_underscores": false, "only_letters": true,
    "max_repeated_char_run": 1, "unique_characters": 5
  },
  "heuristic_score": {
    "score": 74,
    "label": "heuristic",
    "factor_notes": ["minimum possible length (5) — short handles are scarce", "contains no underscores", "letters only"]
  },
  "signals": ["page title: 'Telegram: View @durov'", "..."]
}
```

The heuristic score summarizes **objective traits only** (short handles and clean letter-only handles
tend to be scarcer). It is **not** a market valuation and never represents a price.

### `POST /api/v1/check/bulk`

Request:

```json
{ "usernames": ["yorivex", "@yorixa", "https://t.me/yorzen"] }
```

Response:

```json
{ "success": true, "total": 3, "results": [ /* CheckResponse objects in input order */ ] }
```

* Up to **25 usernames** per request (configurable via `BULK_MAX_USERNAMES`).
* Concurrency is bounded globally (`BULK_CONCURRENCY`, default 5) **and** per upstream
  (`TELEGRAM_CONCURRENCY` default 4, `FRAGMENT_CONCURRENCY` default 2) — hundreds of simultaneous
  upstream requests are never fired.
* Duplicate usernames (after normalization) share a single upstream lookup.

## Vercel deployment

The repo is a ready-to-deploy Vercel project:

* `api/index.py` exposes the FastAPI ASGI app — Vercel's Python runtime serves it natively
  (no extra server, no `vercel dev` special-casing).
* `vercel.json` rewrites **all** routes to that function and caps its duration at 30 s.

Deploy:

```bash
npm i -g vercel
vercel        # from the repo root — answer the prompts (defaults are fine)
vercel --prod
```

or import the repository in the Vercel dashboard ("New Project" →
*Framework Preset: Other*). No build command/output directory is needed; Vercel installs
`requirements.txt` automatically. Optional environment variables can be added under
*Project Settings → Environment Variables*.

Vercel constraints respected: no persistent local DB, no background workers, no filesystem state,
no long-running processes, per-request max duration, stateless TTL cache.

## Environment variables

All optional — sane defaults are built in (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `TELEGRAM_BASE_URL` | `https://t.me` | Telegram pages base URL (override for testing) |
| `FRAGMENT_BASE_URL` | `https://fragment.com` | Fragment base URL |
| `HTTP_USER_AGENT` | Firefox UA string | UA used for public page lookups |
| `HTTP_TIMEOUT_SECONDS` | `8` | Per-attempt upstream timeout |
| `HTTP_MAX_ATTEMPTS` | `3` | Attempts incl. retries (exponential backoff) |
| `HTTP_BACKOFF_BASE_SECONDS` | `0.4` | Backoff base |
| `HTTP_MAX_REDIRECTS` | `5` | Redirect hops followed manually |
| `TELEGRAM_CONCURRENCY` | `4` | Max simultaneous requests to t.me |
| `FRAGMENT_CONCURRENCY` | `2` | Max simultaneous requests to fragment.com |
| `BULK_CONCURRENCY` | `5` | Max simultaneous checks inside one bulk call |
| `BULK_MAX_USERNAMES` | `25` | Bulk size cap (400 above) |
| `CACHE_TTL_SECONDS` | `300` | Result cache TTL (ownership changes!) |
| `CACHE_MAX_ENTRIES` | `2048` | Cache size bound |
| `API_KEYS` | *(empty = off)* | Comma-separated keys; when set, `X-API-Key` is required on `/api/v1/*` |
| `API_KEY_HEADER` | `X-API-Key` | Header used for the API key |
| `RATE_LIMIT_ENABLED` | `false` | Enable tiny per-client in-memory rate limiter |
| `RATE_LIMIT_REQUESTS_PER_MINUTE` | `60` | Rate limiter budget |

Credentials, when configured, are only ever read from the environment and never appear in responses
or logs.

## Status taxonomy

| Status | Meaning |
| --- | --- |
| `taken` | Username currently resolves on Telegram (channel/group/bot page, or a Fragment "taken/claimed" report consistent with a bare user page). |
| `fragment_collectible` | Not publicly resolvable on Telegram, but Fragment tracks it as a collectible (auction / for sale / sold / unavailable / auctionable). Not freely claimable. |
| `available` | Telegram **clearly** does not resolve the handle (HTTP 404 or redirect to `telegram.org`) **and** Fragment has no page for it **and** no upstream check failed. Can change at any moment; claim in the official app to confirm. |
| `invalid` | Input failed local validation; no external request was made. |
| `unknown` | Anything else: inconclusive public signals, upstream failure, rate limit, anti-bot page, or a redesigned upstream page. |

## Explanation of `unknown` — read this before trusting `available`

Public Telegram pages are deliberately minimal in many cases. As verified against the live site
(2026-07-30):

1. **Bare contact pages are ambiguous.** Telegram renders the *identical* bare
   *"If you have Telegram, you can contact @x right away"* page for a registered user with no public
   web metadata (e.g. the official `@support`) **and** for an unclaimed random handle. Neither the
   page title nor the body distinguishes them publicly. The API therefore reports
   `exists: null / page_kind: bare_contact_page` and an overall `unknown` — never a guess either way.
2. **Failure ≠ availability.** Timeouts, DNS/TLS errors, 429s, 5xx, anti-bot challenges and
   `tg://` deep-link redirects produce structured errors or `exists: null`. Upstream problems *never*
   yield `available`.
3. **Discordant signals stay discordant.** If Telegram clearly does not resolve a handle while
   Fragment reports it as claimed, the verdict is `unknown` with the conflict documented.
4. **`available` certification requires two clean negatives** (Telegram + Fragment) and has a short
   cache TTL — ownership and listing state change over time, and Telegram may silently reserve some
   handles.
5. **4-character names, names formerly owned, banned/frozen handles and Fragment-side edge cases**
   may be invisible to public pages entirely. `unknown` is the honest answer in all of these cases.

## Known limitations

* **Entity type is public-signal based.** Channels, groups and bots are reliably distinguishable on
  their public pages; regular users currently expose only bare pages (see above), so a taken
  *user* handle with no public metadata may surface as `unknown` instead of `taken`. This is the
  conservative trade-off required by the "no false availability" rule.
* **Fragment has no documented public API.** The Fragment adapter parses public pages and may need
  updates if Fragment redesigns (it degrades to `unknown`, never to wrong answers). The adapter is
  isolated in `app/fragment.py` for exactly that reason.
* **In-memory cache** is per serverless instance; concurrent cold instances may duplicate a lookup
  occasionally (bounded by the short TTL and per-host concurrency caps).
* **Rate limits are upstream-dependent.** Aggressive bulk usage against Telegram/Fragment may still
  trigger their own throttling; the API honours `Retry-After` and keeps request rates low by design.
* The **heuristic score** resembles rarity, not value. It must never be presented as a market price.

## License

MIT — see [LICENSE](LICENSE).
