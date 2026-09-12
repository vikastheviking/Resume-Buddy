# Resume-Buddy — ATS Resume Architect & Optimizer

[![Node.js](https://img.shields.io/badge/Node.js-18%2B-green.svg)](https://nodejs.org/)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org/)
[![Llama-3.3-70B](https://img.shields.io/badge/AI_Engine-Llama--3.3--70B-orange.svg)](https://groq.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Resume-Buddy rewrites a resume against a target job description and scores the result
for ATS (Applicant Tracking System) compatibility. A Node.js server handles the web
layer — static frontend, file uploads, email verification, OTP auth — and delegates
extraction, scoring, optimization and export to a Python engine it launches and proxies to.

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

**Auth** — email signup/signin with five-layer address verification (RFC 5322 syntax, DNS MX
lookup, disposable-domain blacklist, typo detection, live SMTP `RCPT TO` probe), 6-digit OTP
with rate limiting and constant-time comparison, plus a one-click guest mode for demos.

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
┌──────────────────────────────┐
│   React single-page client   │   web/  →  web/dist
│    (Vite build, no runtime   │
│     framework beyond React)  │
└──────────────┬───────────────┘
               │ HTTP / JSON
               ▼
┌──────────────────────────────┐
│   Node.js (Express Server)   │   server/
│    - Port 3000               │
│    - Static assets & uploads │
│    - Helmet, CORS, rate limits│
│    - 5-layer email validator │
│    - 6-digit OTP service     │
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
│    - Supabase Postgres users │
└──────────────────────────────┘
```

The Node server spawns the Python engine as a child process (`python -m engine.api`),
waits for its health check before accepting traffic, and restarts it with backoff if it
exits. The engine binds to loopback only; the Node process is the sole public entry point.

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
│   ├── auth.py                Supabase Postgres accounts, PBKDF2-HMAC-SHA256 hashing
│   └── sample_data.py         built-in demo resume/JD pairs (synthetic)
├── server/                   Node.js web server
│   ├── index.js               Express app, static hosting, API proxy, engine supervisor
│   ├── email-validator.js     5-layer email verification
│   └── otp-service.js         OTP generation, delivery and verification
├── web/                      React frontend (Vite)
│   ├── index.html             HTML shell
│   └── src/
│       ├── App.jsx            page composition and app state
│       ├── api.js             typed calls to the backend
│       ├── markdown.jsx       renders engine markdown as React elements
│       ├── styles.css         the classic design system
│       └── components/        DocumentInput, ScorePanel, AuditPanel, AuthDialog
├── tests/                    test suites for both runtimes
├── scripts/                  developer utilities
│   └── check_api_key.py       LLM provider key/latency diagnostics
├── docs/deployment.md        cloud deployment guide
├── Dockerfile                multi-runtime production image
├── render.yaml               Render.com blueprint
└── Procfile                  Railway / Fly.io / Heroku entry point
```

User accounts are stored in Supabase Postgres (table `app_users`, see
`supabase_app_users_setup.sql`), accessed via its REST API using the service_role key
(`SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY`). This survives redeploys, unlike a local
file on Render's ephemeral disk.

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

### 3. Build the frontend

```bash
npm run build
```

This compiles the React app into `web/dist`, which the server serves as static files.

### 4. Configure

```bash
cp .env.example .env
```

Set `GROQ_API_KEY` in `.env` — a free key is available at [console.groq.com](https://console.groq.com).
Without it the app still runs, but only the structural pass is available. Live OTP email
delivery is optional; see the comments in `.env.example`.

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

pytest                # offline suite: scorer, extractor, optimizer, auth
pytest -m live        # opt-in: hits the real LLM provider, needs GROQ_API_KEY
npm test              # email validator (performs live DNS/SMTP lookups)
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
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | yes | Supabase Postgres project used for the `app_users` table. See `supabase_app_users_setup.sql`. |
| `CORS_ORIGINS` | no | Comma-separated origin allowlist. Same-origin only when unset. |
| `ENGINE_TIMEOUT_MS` | no | Timeout for engine calls (default `20000`) |
| `OPTIMIZE_TIMEOUT_MS` | no | Timeout for the optimize call, which waits on an LLM (default `120000`) |
| `LLM_BASE_URL` / `LLM_MODEL` | no | Point the client at another OpenAI-compatible provider |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | no | Gmail App Password for live OTP email |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` | no | Custom SMTP instead of Gmail |
| `SSL_KEY_PATH` / `SSL_CERT_PATH` | no | TLS certificate paths for local HTTPS |

---

## Security notes

The Node layer sets CSP and related headers via Helmet, restricts CORS to same-origin
unless `CORS_ORIGINS` is set, rate-limits the API (with tighter budgets on the LLM-backed
optimize route and on auth routes), validates upload type and size, and returns generic
error messages while logging the detail server-side.

Accounts created through the OTP flow are **passwordless**: they store no usable password
hash, and password login against them is refused. Email/password accounts use
PBKDF2-HMAC-SHA256 with a per-user salt.

Sign-in issues a server-signed bearer token (`server/sessions.js`) on successful login,
signup, or OTP verification; `/api/optimize`, `/api/skill-gap-plan`, and the export routes
require a valid one (`requireAuth` in `server/index.js`). Guests get a token too (tagged
distinctly from verified-email ones) rather than bypassing auth entirely. Rate limiting is
per-IP (`express-rate-limit`) in addition to the per-account OTP cooldown.

---

## Deployment

`Dockerfile` (Node + Python in one image), `render.yaml` (Render.com blueprint) and
`Procfile` (Railway, Fly.io, Heroku) are included. See [docs/deployment.md](docs/deployment.md).

User accounts live in Supabase Postgres, not the container filesystem, so they survive
redeploys on platforms with ephemeral disks (Render's free tier included) without needing
a mounted volume.

---

## License

MIT — see [LICENSE](LICENSE).
