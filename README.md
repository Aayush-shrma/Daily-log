# DayLog

A website for the **#100DaysOfCode** crowd. Write a messy daily log and get:

- clean bullets plus an editable, tweet-ready draft (with a Copy button),
- a GitHub-style heatmap coloured by how much you did each day,
- a LeetCode-style streak (current and longest),
- day lookup — on day 100, instantly see what you did on day 10,
- keyword search over your past logs.

There is **no X/Twitter API**. You log inside DayLog and copy the text out.

## Stack

- **Backend:** FastAPI + SQLAlchemy 2.0 (sync), Python 3.11+.
- **Database:** Postgres (Neon) in production; SQLite for tests and local dev.
- **Frontend:** React + Vite + TypeScript + Tailwind CSS v4 + shadcn/ui (Radix) +
  Motion + cmdk + sonner, in `web/`. Built to `web/dist` and served by FastAPI
  from the **same origin**, so the httpOnly cookie and the CSRF Origin check keep
  working. Needs Node 20.19+/22.12+ (developed on Node 24).
- **Auth:** our own — email + password (argon2) and "Continue with Google".
- **LLM:** one hosted provider (Gemini or Groq) via `httpx`, used in exactly one
  function (`clean_log`). Streaks, heatmap levels and counts are plain code.
- **BYOK:** any user can bring their own Gemini/Groq key. It lives in their
  browser and is sent per request in headers; the server never stores or logs it.

## Layout

```
daylog/
├── app/
│   ├── main.py          app, middleware, routers, /health, /
│   ├── config.py        pydantic-settings
│   ├── database.py      engine, SessionLocal, Base, get_db()
│   ├── security.py      hashing, session cookie, get_current_user, origin check, rate limits
│   ├── timeutils.py     the user's local date (DEFAULT_TIMEZONE)
│   ├── models/          user.py, log.py
│   ├── schemas/         user.py, log.py
│   ├── routers/         auth.py, logs.py, stats.py, llm.py
│   └── services/        llm.py, streaks.py, google.py, llm_usage.py
├── web/                 React + Vite frontend (built to web/dist)
│   ├── src/             app shell, features, ui components, lib (heatmap, api)
│   ├── index.html, vite.config.ts, vitest.config.ts, package.json
├── tests/               conftest.py + one file per area
├── scripts/smoke_test.py
├── requirements.txt, .env.example, Dockerfile, render.yaml
```

## Quick start (local)

```bash
cd daylog
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux
pip install -r requirements.txt
copy .env.example .env            # Windows;  cp on macOS/Linux
```

Edit `.env` (see below), then build the frontend once and start the API:

```bash
cd web
npm install
npm run build          # writes web/dist
cd ..
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Interactive API docs are at `/docs`.

### Frontend dev workflow

Pick one of these; both keep production untouched.

**A. Watch build (simplest — no proxy, no extra config).** FastAPI serves
`web/dist`, so just rebuild on change and refresh:

```bash
cd web
npm run build -- --watch     # rebuilds web/dist on every save
```

**B. Vite dev server + proxy (fast HMR).** Vite serves the app on
`http://localhost:5173` and proxies `/auth`, `/logs`, `/stats`, `/llm`, `/health`
to FastAPI on `:8000`. Because the browser's origin is now `:5173`, allow it for
unsafe (POST/PATCH/DELETE) requests via a **dev-only** setting:

```bash
# .env  (never set this in production)
DEV_ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

```bash
# terminal 1
uvicorn app.main:app --reload
# terminal 2
cd web
npm run dev          # http://localhost:5173
```

`DEV_ALLOWED_ORIGINS` defaults to empty, so production only accepts `BASE_URL`'s
origin. Google sign-in redirects to `BASE_URL` (`:8000`), which is fine in dev.

For local development you can leave `DATABASE_URL` as the SQLite default
(`sqlite:///./daylog.db`) — the app creates the tables on startup. Point it at a
Neon **dev** branch when you want to match production.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `APP_NAME` | Shown in the UI/config. |
| `DEBUG` | `true` locally. Keep `false` in production. |
| `BASE_URL` | Public URL of the site. Used for cookies and the Google redirect. Must match the origin the browser uses. |
| `SECRET_KEY` | Signs the session JWT and the OAuth state. Must be a random string of **at least 32 characters**; with `DEBUG=false` or an `https` `BASE_URL` the app refuses to start with a default/short key. `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SESSION_DAYS` | Session lifetime in days (default 7). |
| `DATABASE_URL` | SQLAlchemy URL. Neon: `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require`. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth. Leave empty to hide the Google button. |
| `LLM_PROVIDER` | `gemini` or `groq`. |
| `LLM_API_KEY` | The **shared** server key (optional). Empty ⇒ always use the plain-code fallback. |
| `LLM_MODEL` | Optional model override. Defaults: `gemini-3.8-flash` / `llama-3.3-70b-versatile`. |
| `LLM_TIMEOUT_SECONDS` | Provider request timeout (default 20). |
| `DEFAULT_TIMEZONE` | The user's local date, e.g. `Asia/Kolkata`. Dates are never UTC dates. |
| `DEV_ALLOWED_ORIGINS` | Dev only. Extra origins allowed to make unsafe requests (the Vite dev server). Empty in production so only `BASE_URL`'s origin is accepted. |
| `FORWARDED_ALLOW_IPS` | Docker image only. Proxies whose `X-Forwarded-For`/`-Proto` are trusted. Defaults to `127.0.0.1`; do **not** set `*` (a client could then spoof its IP and defeat the login rate limiter). Set it to your proxy's address if you need real client IPs. |
| `SMOKE_LLM_KEY` | Local smoke test only. Not used by the app. |

Never commit `.env` — it is gitignored.

## Google OAuth setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) → **APIs & Services → Credentials**.
2. **Create credentials → OAuth client ID → Web application**.
3. **Authorised redirect URIs** (add both):
   - `http://127.0.0.1:8000/auth/google/callback` (local)
   - `<BASE_URL>/auth/google/callback` (production, e.g. `https://daylog.onrender.com/auth/google/callback`)
4. Configure the **OAuth consent screen**; while it is in "Testing" add your own
   Google account under **Test users**.
5. Copy the client ID and secret into `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
   and set `BASE_URL` to the matching origin.

The callback uses `f"{BASE_URL}/auth/google/callback"` (not the request host),
so it stays correct behind a proxy.

## Neon setup

1. Create a project at [neon.tech](https://neon.tech) and a **development branch**
   (plus a separate `production` branch).
2. Copy the connection string and change the prefix to `postgresql+psycopg://`,
   keeping `sslmode=require`:
   `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require`
3. Put the **dev** string in your local `.env`; put the **production** string in
   the deploy environment. Never point local dev at production data.

The engine uses `pool_pre_ping=True` and `pool_recycle=300` because Neon scales
to zero and drops idle connections. Tables are created on startup
(`Base.metadata.create_all`) — fine for v1.

## LLM providers

The request formats were taken from the official docs:

- **Gemini** — `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`, header `x-goog-api-key`.
- **Groq** — `POST https://api.groq.com/openai/v1/chat/completions` (OpenAI-compatible), header `Authorization: Bearer <key>`.

Only these two fixed hosts are ever called; `provider` and `model` are validated
before use, so a user's key can never be sent to an attacker's server.

## Bring your own key (BYOK)

Open **Settings → Bring your own key** in the UI, pick a provider, paste a key,
optionally a model, choose "Remember on this device" (`localStorage`, otherwise
`sessionStorage`), then **Save key** / **Test key** / **Clear key**. Saved keys
show only their last 4 characters.

On `POST /logs`, `POST /logs/{id}/regenerate` and `POST /llm/check` the browser
sends `X-LLM-Provider`, `X-LLM-Key` and optional `X-LLM-Model`. Priority per
request: **the user's key → the server's `LLM_API_KEY` → the plain-code
fallback**. Keys are never stored, logged, echoed or placed in a URL.

Calls that use the **server's** key are capped at 20 per user per day; past that
the app falls back and asks you to add your own key.

## Testing

```bash
pytest                    # backend
cd web && npm test        # frontend: heatmap grid builder + streak display (Vitest)
```

Backend tests use a throwaway SQLite file and never touch the network, Neon,
Google or an LLM (those are mocked). The heatmap column builder — including
month spacers, partial first/last columns, a year boundary and today on each
weekday — is covered by the Vitest suite (the tests that used to shell out to a
Node script were replaced by it). The tests that exercise the served frontend
skip when `web/dist` has not been built.

Smoke test against a running server:

```bash
# in one terminal
uvicorn app.main:app --reload
# in another
python scripts/smoke_test.py
```

It signs up a throwaway user, exercises the API, prints PASS/FAIL per step and
deletes the user at the end.

## Deploy (Vercel)

DayLog is deployed on Vercel: [https://daylog-v1.vercel.app](https://daylog-v1.vercel.app).

The project uses FastAPI for the backend and React + Vite for the frontend. Vercel handles deployment and provides the public URL.

### Environment variables

Configure the required environment variables in your Vercel project under **Settings → Environment Variables**.

| Variable | Purpose |
| --- | --- |
| `BASE_URL` | `https://daylog-v1.vercel.app` |
| `SECRET_KEY` | A random secret string of at least 32 characters. |
| `DATABASE_URL` | Your Neon production PostgreSQL connection string using `postgresql+psycopg://` and `sslmode=require`. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth credentials. |
| `LLM_PROVIDER` | `gemini` or `groq`. |
| `LLM_API_KEY` | Optional shared server-side LLM API key. |
| `LLM_MODEL` | Optional model override. |
| `LLM_TIMEOUT_SECONDS` | LLM request timeout. |
| `DEFAULT_TIMEZONE` | `Asia/Kolkata` by default. |
| `DEBUG` | Keep `false` in production. |

Set the environment variables required by your enabled features. Never commit `.env` or expose server-side secrets in frontend environment variables.

### Google OAuth

In Google Cloud Console, configure the authorised redirect URI to match your deployed backend:

`https://daylog-v1.vercel.app/auth/google/callback`

Also configure the local callback if you use Google sign-in during local development.

Update `BASE_URL` and the Google OAuth redirect URI whenever your production domain changes.

### Database

DayLog uses Neon PostgreSQL in production and SQLite for local development and tests. Keep development and production databases separate, and configure the production connection string in Vercel's environment variables.

### Local development

For local setup, testing, and frontend development, follow the Quick start and Frontend dev workflow sections above.

For backend tests, run `pytest`. For frontend tests, run `cd web && npm test`.

### Deployment notes

- Production credentials must be configured in Vercel's environment settings.
- Verify that API routes, database connections, authentication cookies, Google OAuth callbacks, and frontend asset serving work correctly in the deployed environment.
- The deployment configuration must support FastAPI API routes and the built frontend. Do not assume that Render-specific Docker settings or start commands work unchanged on Vercel.
- Run the smoke test against a running deployment when appropriate, using a test account and avoiding production data.

