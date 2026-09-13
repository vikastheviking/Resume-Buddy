# Resume-Buddy — ATS Resume Architect & Optimizer

[![Node.js](https://img.shields.io/badge/Node.js-18%2B-green.svg)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org/)
[![Llama-3.3-70B](https://img.shields.io/badge/AI_Engine-Llama--3.3--70B-orange.svg)](https://groq.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Resume-Buddy rewrites a resume against a target job description and scores the result
for ATS (Applicant Tracking System) compatibility. A Node.js server handles the web
layer — static frontend, file uploads, email deliverability checks — and delegates
extraction, scoring, optimization and export to a Python engine it launches and proxies
to. Authentication, user accounts, and OTP email delivery are all handled by Supabase
Auth, not by this app itself.

---

## Features

**Input** — paste text or drag-and-drop `.pdf` / `.docx` / `.txt` for both the resume and
the job description, with automatic text extraction and keyword parsing.

**Scoring** — a score for the original resume, a score for the rewrite, and the movement
between them, broken down into keyword coverage, semantic alignment, quantified impact and
ATS format hygiene. The result panel lists which job-description terms the rewrite actually
picked up and which are still missing, so the number is backed by visible evidence.

**Output** — a single-column, ATS-parseable resume (no tables or graphics) rewritten by
Llama-3.3-70B, exportable to ATS-clean PDF or DOCX.

**Auth** — email sign-in/sign-up via Supabase Auth's passwordless email-code flow, with a
four-layer deliverability pre-check (RFC 5322 syntax, DNS MX lookup, disposable-domain
blacklist, typo detection) before a code is ever sent, plus a one-click anonymous guest
mode for demos. Full name and phone are collected on sign-up and checked for uniqueness
before Supabase issues a code, so Sign In and Create Account never silently do the wrong
thing.

---

## How scoring works

The score is a weighted blend of four measurements: keyword coverage (45%), semantic
alignment (30%), quantified impact (15%) and ATS format hygiene (10%).

Two properties the engine holds to:

- **Scores are measured, never targeted.** There is no floor and no boost. If a rewrite
  does not improve the score, the UI says so rather than showing a gain.
- **Nothing is invented.** Neither the LLM prompt nor the offline path may add an employer,
  a date, a credential or a metric that is not in your original resume. A resume that
  claims work you did not do fails the interview, not just the filter.

When no API key is configured, or the provider is unreachable, the engine falls back to a
**structural pass**: it reorganises your existing text into clean ATS sections and bullets
without changing a word. That is genuinely useful — bad formatting is a real ATS failure
mode — but it will not raise keyword coverage, and the result panel labels it clearly.

---

## Architecture

```
┌──────────────────────────────┐        ┌──────────────────────────┐
│   React single-page client   │───────▶│      Supabase Auth       │
│    (Vite build, no runtime   │  direct│  accounts, sessions,     │
│     framework beyond React)  │        │  OTP email delivery      │
└──────────────┬───────────────┘        └──────────────────────────┘
               │ HTTP / JSON (Bearer <supabase access token>)
               ▼
┌──────────────────────────────┐
│   Node.js (Express Server)   │   server/
│    - Port 3000               │
│    - Static assets & uploads │
│    - Helmet, CORS, rate limits│
│    - 4-layer email validator │
│    - Verifies Supabase JWTs  │
│    - Account existence check │
└──────────────┬───────────────┘
               │ internal reverse-proxy to 127.0.0.1:5001
               ▼
┌──────────────────────────────┐
│     Python ATS Engine        │   engine/
│    - Starlette / Uvicorn     │
│    - PDF / DOCX extractor    │
│    - Keyword & impact scorer │
│    - Groq Llama-3.3-70B      │
│    - PDF / DOCX exporter     │
└──────────────────────────────┘
```

The Node server spawns the Python engine as a child process (`python -m engine.api`),
waits for its health check before accepting traffic, and restarts it with backoff if it
exits. The engine binds to loopback only; the Node process is the sole public entry point
for the API. The browser talks to Supabase directly for authentication (using the public
anon key) - Node never sees a password or OTP code, only the resulting access token.

---

## Repository layout

```
.
├── engine/                   Python ATS engine (importable package)
│   ├── api.py                 Starlette REST API — the service the Node server proxies to
│   ├── extractor.py           PDF/DOCX/text extraction and section parsing
│   ├── scorer.py              ATS compatibility scoring
│   ├── optimizer.py           LLM-driven rewrite against a job description
│   ├── exporter.py            ATS-clean PDF and DOCX rendering
│   ├── llm_client.py          provider-agnostic LLM transport
│   └── sample_data.py         built-in demo resume/JD pairs (synthetic)
├── server/                   Node.js web server
│   ├── index.js               Express app, static hosting, API proxy, engine supervisor,
│   │                           Supabase JWT verification, account existence check
│   └── email-validator.js     4-layer email deliverability pre-check
├── web/                      React frontend (Vite)
│   ├── index.html             HTML shell
│   └── src/
│       ├── App.jsx            page composition, app state, Supabase session sync
│       ├── api.js             typed calls to the Node backend
│       ├── supabaseClient.js  browser Supabase client (auth only)
│       ├── markdown.jsx       renders engine markdown as React elements
│       ├── styles.css         the classic design system
│       └── components/        DocumentInput, ScorePanel, AuditPanel, AuthDialog
├── tests/                    test suites for both runtimes
├── scripts/                  developer utilities
│   └── check_api_key.py       LLM provider key/latency diagnostics
├── docs/deployment.md        cloud deployment guide
├── supabase_profiles_setup.sql  one-time Supabase SQL migration (profiles table + trigger)
├── Dockerfile                multi-runtime production image
├── render.yaml               Render.com blueprint
└── Procfile                  Railway / Fly.io / Heroku entry point
```

User accounts, sessions, and OTP email delivery all live in Supabase Auth - Render only
ever hosts the app, never the account data or the email-sending step. `profiles` (see
`supabase_profiles_setup.sql`) stores full name/phone alongside each Supabase Auth user,
kept in sync by a database trigger.

---

## Quick start

### 1. Clone

```bash
git clone https://github.com/vikastheviking/Resume-Buddy.git
cd Resume-Buddy
```

### 2. Install dependencies

```bash
npm install
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

Set `GROQ_API_KEY` in `.env` — a free key is available at [console.groq.com](https://console.groq.com).
Without it the app still runs, but only the structural pass is available.

Set `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` (and the matching
`VITE_` copies of the first two) — see the comments in `.env.example` for where to find
them and the one-time SQL migration to run first. Without these, sign-in/sign-up will not
work at all.

### 4. Build the frontend

```bash
npm run build
```

This compiles the React app into `web/dist`, which the server serves as static files.
**Do this after step 3, not before** - Vite reads the `VITE_SUPABASE_*` variables from
`.env` at build time and bakes them into the bundle; building first ships a frontend that
can't reach Supabase at all.

### 5. Run

```bash
npm start
```

Then open **http://localhost:3000**. The Python engine starts automatically.

---

## Running the pieces individually

Start only the Python API (defaults to port 5001, override with `PYTHON_PORT`):

```bash
python -m engine.api
```

Develop the frontend with hot reload. Vite serves on :5173 and proxies `/api` to the
Node server, so run `npm start` in another terminal alongside it:

```bash
npm run dev:web
```

Diagnose an LLM provider key — status, latency and error detail:

```bash
python scripts/check_api_key.py
```

---

## Tests

```bash
pip install -r requirements-dev.txt

pytest                # offline suite: scorer, extractor, optimizer, skill-gap, API
pytest -m live        # opt-in: hits the real LLM provider, needs GROQ_API_KEY
npm test              # email validator (performs live DNS lookups)
```

`pytest` runs offline and deterministically by default; tests that make real network calls
are marked `live` and deselected. Configuration lives in `pyproject.toml`, which puts the
repo root on the path so `engine.*` imports resolve without any `sys.path` manipulation.

---

## Configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `GROQ_API_KEY` | for AI rewrites | LLM key. Without it, only the structural pass runs. |
| `PORT` | no | Node web server port (default `3000`) |
| `PYTHON_PORT` | no | Python engine port (default `5001`) |
| `PYTHON_BIN` | no | Interpreter used to spawn the engine (default `python`) |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` / `SUPABASE_SERVICE_ROLE_KEY` | yes | Auth, sessions, and the `profiles` table. See `.env.example` and `supabase_profiles_setup.sql`. |
| `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | yes | Same values as above, built into the frontend bundle at build time (the browser talks to Supabase directly). |
| `CORS_ORIGINS` | no | Comma-separated origin allowlist. Same-origin only when unset. |
| `ENGINE_TIMEOUT_MS` | no | Timeout for engine calls (default `20000`) |
| `OPTIMIZE_TIMEOUT_MS` | no | Timeout for the optimize call, which waits on an LLM (default `120000`) |
| `LLM_BASE_URL` / `LLM_MODEL` | no | Point the client at another OpenAI-compatible provider |
| `SSL_KEY_PATH` / `SSL_CERT_PATH` | no | TLS certificate paths for local HTTPS |

---

## Security notes

The Node layer sets CSP and related headers via Helmet, restricts CORS to same-origin
unless `CORS_ORIGINS` is set, rate-limits the API (with tighter budgets on the LLM-backed
optimize route and on auth routes), validates upload type and size, and returns generic
error messages while logging the detail server-side.

Accounts are entirely passwordless, managed by Supabase Auth: identity is proven by
controlling the mailbox (email OTP), not a password this app never stores. Sign-in
requires the account to already exist; Create Account requires the email and phone to
both be free - checked server-side (`/api/auth/check-availability` in `server/index.js`,
against the `profiles` table) before Supabase ever sends a code.

The browser holds a genuine Supabase access token (JWT) after signing in; `/api/optimize`,
`/api/skill-gap-plan`, and the export routes require a valid one (`requireAuth` in
`server/index.js`, verified via `supabase.auth.getUser(token)`). Guests get a real
(anonymous) Supabase session too, via `supabase.auth.signInAnonymously()`, rather than
bypassing auth entirely. Rate limiting is per-IP (`express-rate-limit`) on top of
whatever Supabase itself enforces per-account for OTP requests.

---

## Deployment

`Dockerfile` (Node + Python in one image), `render.yaml` (Render.com blueprint) and
`Procfile` (Railway, Fly.io, Heroku) are included. See [docs/deployment.md](docs/deployment.md).

User accounts, sessions, and OTP email delivery all live in Supabase, not the container
filesystem or Render's own outbound network - they survive redeploys on platforms with
ephemeral disks (Render's free tier included) without needing a mounted volume, and email
delivery isn't subject to whatever that platform allows or blocks outbound.

---

## License

MIT — see [LICENSE](LICENSE).
