/**
 * Web server for Resume-Buddy.
 *
 * Serves the frontend, handles uploads and email/OTP auth, and supervises the Python
 * ATS engine it proxies to. The engine listens on loopback only; this process is the
 * sole public entry point.
 */

const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const multer = require('multer');
const { spawn } = require('child_process');
const { createClient } = require('@supabase/supabase-js');
const { verifyRealEmail } = require('./email-validator');
require('dotenv').config();

// Repo root: this file lives in server/, everything else resolves from one level up.
const ROOT_DIR = path.join(__dirname, '..');
const PYTHON_BIN = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'py' : 'python');

const app = express();
const PORT = process.env.PORT || 3000;
const PYTHON_PORT = process.env.PYTHON_PORT || 5001;
const PYTHON_BASE_URL = `http://127.0.0.1:${PYTHON_PORT}`;
const IS_PRODUCTION = process.env.NODE_ENV === 'production';

// Authentication and account storage both live in Supabase now, not this process.
// `supabase` (anon key) only ever verifies a bearer token a client already holds;
// `supabaseAdmin` (service_role, bypasses RLS) is for the availability check below,
// which has to see across all users rather than just the caller's own row.
if (!process.env.SUPABASE_URL || !process.env.SUPABASE_ANON_KEY || !process.env.SUPABASE_SERVICE_ROLE_KEY) {
  console.error('[Supabase] SUPABASE_URL, SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY must all be set.');
}
const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_ANON_KEY);
const supabaseAdmin = process.env.SUPABASE_SERVICE_ROLE_KEY
  ? createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY)
  : null;

/** Express middleware: requires a valid Supabase access token in Authorization: Bearer <token>. */
async function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const [scheme, token] = header.split(' ');
  if (scheme !== 'Bearer' || !token) {
    return res.status(401).json({ error: 'Sign in to use this feature.' });
  }
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data?.user) {
    return res.status(401).json({ error: 'Your session has expired. Please sign in again.' });
  }
  req.user = data.user;
  next();
}

// How long to wait on the engine. Optimization runs an LLM call, so it gets its own
// budget; everything else should answer promptly.
const ENGINE_TIMEOUT_MS = Number(process.env.ENGINE_TIMEOUT_MS || 20000);
const OPTIMIZE_TIMEOUT_MS = Number(process.env.OPTIMIZE_TIMEOUT_MS || 120000);

const MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
const ALLOWED_UPLOAD_EXTENSIONS = new Set(['.pdf', '.docx', '.doc', '.txt', '.md']);
const ALLOWED_UPLOAD_MIMETYPES = new Set([
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
  'application/octet-stream', // browsers send this for .docx surprisingly often
]);

// ---------------------------------------------------------------------------
// 1. Middleware
// ---------------------------------------------------------------------------

app.set('trust proxy', 1); // required for correct client IPs behind Render/Railway/Fly

app.use(helmet({
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'"],
      // The markup carries inline style attributes; fonts come from Google Fonts.
      styleSrc: ["'self'", 'https://fonts.googleapis.com', "'unsafe-inline'"],
      fontSrc: ["'self'", 'https://fonts.gstatic.com'],
      imgSrc: ["'self'", 'data:'],
      // The browser calls Supabase directly (signInWithOtp/verifyOtp/session refresh) -
      // without this, CSP silently blocks every one of those requests.
      connectSrc: ["'self'", process.env.SUPABASE_URL].filter(Boolean),
      objectSrc: ["'none'"],
      frameAncestors: ["'none'"],
      baseUri: ["'self'"],
      formAction: ["'self'"],
    },
  },
  crossOriginEmbedderPolicy: false,
}));

// Same-origin by default. Set CORS_ORIGINS to a comma-separated allowlist to open it up.
const corsOrigins = (process.env.CORS_ORIGINS || '')
  .split(',')
  .map((o) => o.trim())
  .filter(Boolean);
app.use(cors(corsOrigins.length ? { origin: corsOrigins, credentials: true } : { origin: false }));

app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true, limit: '2mb' }));

class UploadRejected extends Error {}

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: MAX_UPLOAD_BYTES, files: 1 },
  fileFilter: (req, file, cb) => {
    const ext = path.extname(file.originalname || '').toLowerCase();
    if (!ALLOWED_UPLOAD_EXTENSIONS.has(ext)) {
      return cb(new UploadRejected(`Unsupported file type "${ext || 'unknown'}". Upload a PDF, DOCX, or TXT file.`));
    }
    if (file.mimetype && !ALLOWED_UPLOAD_MIMETYPES.has(file.mimetype)) {
      return cb(new UploadRejected('The uploaded file does not look like a document.'));
    }
    cb(null, true);
  },
});

// The React app is built by Vite into web/dist. Hashed asset filenames make them
// safe to cache hard; index.html must not be, or clients pin an old build.
const CLIENT_DIR = path.join(ROOT_DIR, 'web', 'dist');
const CLIENT_INDEX = path.join(CLIENT_DIR, 'index.html');

if (!fs.existsSync(CLIENT_INDEX)) {
  console.warn('[web] web/dist is missing — run `npm run build` to compile the frontend.');
}

app.use(express.static(CLIENT_DIR, {
  index: false,
  maxAge: IS_PRODUCTION ? '1y' : '0',
  setHeaders: (res, filePath) => {
    if (filePath.endsWith('index.html')) res.setHeader('Cache-Control', 'no-cache');
  },
}));

// Rate limits. Optimization is the expensive path (it spends LLM tokens); OTP dispatch
// sends real email. Both are limited per client IP, which the per-email cooldown in the
// OTP service cannot do on its own.
const rateLimitOptions = { standardHeaders: 'draft-7', legacyHeaders: false };

const generalLimiter = rateLimit({
  ...rateLimitOptions,
  windowMs: 15 * 60 * 1000,
  limit: 300,
  message: { error: 'Too many requests. Please slow down and try again shortly.' },
});

const optimizeLimiter = rateLimit({
  ...rateLimitOptions,
  windowMs: 15 * 60 * 1000,
  limit: 20,
  message: { error: 'Optimization limit reached. Please wait a few minutes before trying again.' },
});

const authLimiter = rateLimit({
  ...rateLimitOptions,
  windowMs: 15 * 60 * 1000,
  limit: 15,
  message: { success: false, error: 'Too many authentication attempts. Please wait a few minutes.' },
});

app.use('/api/', generalLimiter);

// ---------------------------------------------------------------------------
// 2b. Global daily LLM-call budget
// ---------------------------------------------------------------------------
//
// The per-IP optimizeLimiter above bounds any one visitor, but not the total across
// everyone — Gemini/Groq's free tiers have a shared daily quota per account, not per
// visitor, so a link that gets shared around can burn through it. Once that happens,
// every further LLM-backed call would otherwise fail and silently fall back (optimize)
// or come back empty (skill-gap plan), which looks like the app breaking rather than
// what it actually is (today's free quota being used up). This turns that into an
// explicit, friendly message instead, and — since it's checked before proxying to the
// engine — stops those calls from ever reaching the LLM provider at all. Shared across
// every LLM-backed route (optimize, skill-gap plan), not per-route, since they draw on
// the same underlying provider quota.
const DAILY_LLM_CALL_LIMIT = Number(process.env.DAILY_LLM_CALL_LIMIT || 150);
let llmBudget = { count: 0, resetAt: nextUtcMidnight() };

function nextUtcMidnight() {
  const now = new Date();
  return Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1);
}

/** True and increments the counter if today's shared LLM-call budget has room; false if not. */
function tryConsumeLlmBudget() {
  if (Date.now() >= llmBudget.resetAt) {
    llmBudget = { count: 0, resetAt: nextUtcMidnight() };
  }
  if (llmBudget.count >= DAILY_LLM_CALL_LIMIT) return false;
  llmBudget.count += 1;
  return true;
}

// ---------------------------------------------------------------------------
// 2. Python engine lifecycle
// ---------------------------------------------------------------------------

let pythonProcess = null;
let shuttingDown = false;
let restartAttempts = 0;

/** fetch against the engine with a hard timeout, so a hung engine cannot pin a request. */
async function engineFetch(pathname, options = {}, timeoutMs = ENGINE_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${PYTHON_BASE_URL}${pathname}`, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function checkPythonHealth() {
  try {
    const res = await engineFetch('/api/health', { method: 'GET' }, 3000);
    if (!res.ok) return false;
    const data = await res.json();
    return data.status === 'healthy';
  } catch {
    return false;
  }
}

function spawnEngine() {
  console.log(`[engine] launching engine.api on port ${PYTHON_PORT}...`);
  // Run as a package module from the repo root so `engine.*` imports resolve.
  pythonProcess = spawn(PYTHON_BIN, ['-m', 'engine.api'], {
    cwd: ROOT_DIR,
    env: { ...process.env, PYTHON_PORT: String(PYTHON_PORT), PYTHONUNBUFFERED: '1' },
    stdio: 'pipe',
  });

  pythonProcess.stdout.on('data', (d) => console.log(`[engine] ${d.toString().trim()}`));
  pythonProcess.stderr.on('data', (d) => console.error(`[engine] ${d.toString().trim()}`));

  pythonProcess.on('close', (code) => {
    pythonProcess = null;
    if (shuttingDown) return;

    // Restart with backoff. Without this a single engine crash takes the app down until
    // someone notices and restarts it by hand.
    restartAttempts += 1;
    const delay = Math.min(30000, 1000 * 2 ** (restartAttempts - 1));
    console.error(`[engine] exited with code ${code}; restarting in ${delay}ms (attempt ${restartAttempts})`);
    setTimeout(() => {
      if (!shuttingDown) spawnEngine();
    }, delay);
  });
}

async function startPythonBackend() {
  if (await checkPythonHealth()) {
    console.log(`[engine] already active on port ${PYTHON_PORT}`);
    return true;
  }

  spawnEngine();

  for (let attempt = 0; attempt < 40; attempt += 1) {
    await new Promise((r) => setTimeout(r, 500));
    if (await checkPythonHealth()) {
      restartAttempts = 0;
      console.log('[engine] ready');
      return true;
    }
  }

  console.warn('[engine] did not become healthy within 20s; continuing to retry in the background');
  return false;
}

// ---------------------------------------------------------------------------
// 3. Helpers
// ---------------------------------------------------------------------------

/**
 * Log the real error, return a safe one.
 *
 * Raw `err.message` values leak engine internals, file paths and dependency versions to
 * anyone who can trigger an error, so they stay in the server log.
 */
function fail(res, status, publicMessage, err, shape = 'error') {
  if (err) console.error(`[${status}] ${publicMessage}:`, err.message || err);
  const body = shape === 'success'
    ? { success: false, error: publicMessage }
    : { error: publicMessage };
  if (!IS_PRODUCTION && err) body.details = err.message || String(err);
  return res.status(status).json(body);
}

/** Proxy a JSON request to the engine and relay its response verbatim. */
async function proxyJson(res, pathname, payload, { timeoutMs = ENGINE_TIMEOUT_MS, label } = {}) {
  const engineRes = await engineFetch(pathname, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }, timeoutMs);

  const text = await engineRes.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    console.error(`[${label}] engine returned non-JSON:`, text.slice(0, 300));
    return res.status(502).json({ error: 'The optimization engine returned an unreadable response.' });
  }
  return res.status(engineRes.status).json(data);
}

function isAbort(err) {
  return err && (err.name === 'AbortError' || err.name === 'TimeoutError');
}

// ---------------------------------------------------------------------------
// 4. API routes
// ---------------------------------------------------------------------------

app.get('/api/health', async (req, res) => {
  const engineOk = await checkPythonHealth();
  res.json({
    status: 'ok',
    server: 'Node.js Express',
    port: PORT,
    engine: engineOk ? 'online' : 'reconnecting',
  });
});

app.get('/api/sample', async (req, res) => {
  try {
    const key = typeof req.query.key === 'string' ? req.query.key : '';
    const engineRes = await engineFetch(`/api/sample?key=${encodeURIComponent(key)}`);
    res.status(engineRes.status).json(await engineRes.json());
  } catch (err) {
    return fail(res, 502, 'Could not load sample data.', err);
  }
});

app.post('/api/auth/validate-email', authLimiter, async (req, res) => {
  try {
    const { email } = req.body || {};
    if (!email) {
      return res.status(400).json({ isValid: false, error: 'Email is required.' });
    }
    res.json(await verifyRealEmail(email));
  } catch (err) {
    return fail(res, 500, 'Could not validate that email address.', err);
  }
});

// Reports whether an email/phone already has an account, using the profiles table
// (kept in sync with auth.users by a database trigger - see supabase_profiles_setup.sql).
// This is what makes Sign In and Create Account behave differently: Sign In needs the
// email to exist, Create Account needs the email and phone to both be free. Needs the
// service_role key because RLS on `profiles` only lets a user read their own row.
app.post('/api/auth/check-availability', authLimiter, async (req, res) => {
  try {
    const { email, phone } = req.body || {};
    if (!email && !phone) {
      return res.status(400).json({ error: 'email or phone is required.' });
    }
    if (!supabaseAdmin) {
      return res.status(500).json({ error: 'Server is not configured for account existence checks.' });
    }

    const result = {};

    if (email) {
      const { data, error } = await supabaseAdmin
        .from('profiles')
        .select('id')
        .eq('email', email.trim().toLowerCase())
        .maybeSingle();
      if (error) throw error;
      result.emailExists = !!data;
    }

    if (phone) {
      const { data, error } = await supabaseAdmin
        .from('profiles')
        .select('id')
        .eq('phone', phone.trim())
        .maybeSingle();
      if (error) throw error;
      result.phoneExists = !!data;
    }

    res.json(result);
  } catch (err) {
    return fail(res, 502, 'Could not check account availability.', err);
  }
});

app.post('/api/upload', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No resume file uploaded.' });
    }

    const formData = new FormData();
    const blob = new Blob([req.file.buffer], { type: req.file.mimetype || 'application/octet-stream' });
    formData.append('file', blob, req.file.originalname);

    // A PDF with a real text layer extracts almost instantly, but the OCR fallback
    // (scanned/photographed PDFs) renders and reads a page as an image - measured over
    // 20s for a single dense page on Render's free-tier CPU (well under a second on a
    // dev machine). Render's own platform proxy kills the whole connection at roughly
    // 30s regardless of any timeout configured here - confirmed live, Render returns
    // its own branded error page at that point, not this app's - so this Node-level
    // timeout only needs to be long enough to let the engine's own OCR budget
    // (engine/extractor.py, currently 20s) finish and reply on its own; it can never
    // usefully be longer than Render's ~30s ceiling anyway.
    const engineRes = await engineFetch('/api/extract', { method: 'POST', body: formData }, 25000);
    const data = await engineRes.json();
    return res.status(engineRes.status).json(data);
  } catch (err) {
    if (isAbort(err)) {
      return fail(res, 504, 'Text extraction timed out. Try a smaller file.', err);
    }
    return fail(res, 502, 'Could not extract text from that file.', err);
  }
});

// Scoring alone costs no LLM tokens — it's pure local computation — so unlike
// /api/optimize it stays free of the auth gate. A visitor can see how their resume
// actually matches a job before committing to sign in for the full rewrite.
app.post('/api/score', async (req, res) => {
  try {
    const { resume_text: resumeText, jd_text: jdText } = req.body || {};
    if (!resumeText || !jdText) {
      return res.status(400).json({ error: 'Both resume_text and jd_text are required.' });
    }
    return await proxyJson(res, '/api/score', { resume_text: resumeText, jd_text: jdText }, { label: 'score' });
  } catch (err) {
    return fail(res, 502, 'Could not score that resume.', err);
  }
});

app.post('/api/optimize', requireAuth, optimizeLimiter, async (req, res) => {
  try {
    const { resume_text: resumeText, jd_text: jdText } = req.body || {};
    if (!resumeText || !jdText) {
      return res.status(400).json({ error: 'Both resume_text and jd_text are required.' });
    }
    if (!tryConsumeLlmBudget()) {
      return res.status(429).json({
        error: "Today's free AI-rewrite quota has been used up so the app stays free for "
          + 'everyone. Try "Check score" for a free baseline check, or come back tomorrow '
          + 'for a full AI rewrite.',
      });
    }
    return await proxyJson(
      res,
      '/api/optimize',
      { resume_text: resumeText, jd_text: jdText },
      { timeoutMs: OPTIMIZE_TIMEOUT_MS, label: 'optimize' },
    );
  } catch (err) {
    if (isAbort(err)) {
      return fail(res, 504, 'Optimization timed out. Please try again.', err);
    }
    return fail(res, 502, 'The optimization engine is unavailable.', err);
  }
});

app.post('/api/skill-gap-plan', requireAuth, optimizeLimiter, async (req, res) => {
  try {
    const { jd_text: jdText, gap_keywords: gapKeywords } = req.body || {};
    if (!jdText || !Array.isArray(gapKeywords) || gapKeywords.length === 0) {
      return res.status(400).json({ error: 'jd_text and a non-empty gap_keywords list are required.' });
    }
    if (!tryConsumeLlmBudget()) {
      return res.status(429).json({
        error: "Today's free AI quota has been used up so the app stays free for everyone. "
          + 'Please come back tomorrow for a skill-gap plan.',
      });
    }
    return await proxyJson(
      res,
      '/api/skill-gap-plan',
      { jd_text: jdText, gap_keywords: gapKeywords },
      { timeoutMs: OPTIMIZE_TIMEOUT_MS, label: 'skill-gap-plan' },
    );
  } catch (err) {
    if (isAbort(err)) {
      return fail(res, 504, 'Generating the skill-gap plan timed out. Please try again.', err);
    }
    return fail(res, 502, 'The skill-gap plan engine is unavailable.', err);
  }
});

/** PDF and DOCX exports differ only in route, media type and filename. */
function registerExport(route, enginePath, mediaType, filename) {
  app.post(route, requireAuth, async (req, res) => {
    try {
      const { markdown_text: markdownText } = req.body || {};
      if (!markdownText || !markdownText.trim()) {
        return res.status(400).json({ error: 'markdown_text is required.' });
      }

      const engineRes = await engineFetch(enginePath, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown_text: markdownText }),
      }, 45000);

      if (!engineRes.ok) {
        return res.status(engineRes.status).json({ error: 'Document generation failed.' });
      }

      res.setHeader('Content-Type', mediaType);
      res.setHeader('Content-Disposition', `attachment; filename="${filename}"`);
      res.send(Buffer.from(await engineRes.arrayBuffer()));
    } catch (err) {
      if (isAbort(err)) {
        return fail(res, 504, 'Document generation timed out.', err);
      }
      return fail(res, 502, 'Document generation failed.', err);
    }
  });
}

registerExport('/api/export/pdf', '/api/export/pdf', 'application/pdf', 'ATS_Optimized_Resume.pdf');
registerExport(
  '/api/export/docx',
  '/api/export/docx',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'ATS_Optimized_Resume.docx',
);

// Unknown API routes must not fall through to the SPA shell: an XHR expecting JSON
// should get a JSON 404, not a page of HTML.
app.use('/api', (req, res) => {
  res.status(404).json({ error: `Unknown API endpoint: ${req.method} /api${req.path}` });
});

// SPA fallback for everything else.
app.get('*', (req, res) => {
  if (!fs.existsSync(CLIENT_INDEX)) {
    return res
      .status(503)
      .type('text/plain')
      .send('Frontend has not been built yet. Run `npm run build`, then reload.');
  }
  return res.sendFile(CLIENT_INDEX);
});

// Multer and body-parser surface their own errors; translate them into clean JSON.
app.use((err, req, res, next) => {
  if (err instanceof UploadRejected) {
    return res.status(415).json({ error: err.message });
  }
  if (err && err.code === 'LIMIT_FILE_SIZE') {
    return res.status(413).json({ error: `File is too large. The maximum size is ${MAX_UPLOAD_BYTES / (1024 * 1024)}MB.` });
  }
  if (err && err.type === 'entity.too.large') {
    return res.status(413).json({ error: 'Request body is too large.' });
  }
  if (res.headersSent) return next(err);
  return fail(res, 500, 'Unexpected server error.', err);
});

// ---------------------------------------------------------------------------
// 5. Startup and shutdown
// ---------------------------------------------------------------------------

const servers = [];

async function startServer() {
  await startPythonBackend();

  const httpServer = http.createServer(app);
  servers.push(httpServer);
  httpServer.listen(PORT, () => {
    console.log('====================================================');
    console.log(' Resume-Buddy — ATS Resume Architect');
    console.log(` Web:    http://localhost:${PORT}`);
    console.log(` Engine: http://127.0.0.1:${PYTHON_PORT}`);
    console.log('====================================================');
  });

  const sslKeyPath = process.env.SSL_KEY_PATH || path.join(ROOT_DIR, 'cert', 'key.pem');
  const sslCertPath = process.env.SSL_CERT_PATH || path.join(ROOT_DIR, 'cert', 'cert.pem');
  const HTTPS_PORT = process.env.HTTPS_PORT || 3443;

  if (fs.existsSync(sslKeyPath) && fs.existsSync(sslCertPath)) {
    try {
      const httpsServer = https.createServer(
        { key: fs.readFileSync(sslKeyPath), cert: fs.readFileSync(sslCertPath) },
        app,
      );
      servers.push(httpsServer);
      httpsServer.listen(HTTPS_PORT, () => {
        console.log(` HTTPS:  https://localhost:${HTTPS_PORT}`);
      });
    } catch (err) {
      console.warn('[https] could not initialise TLS:', err.message);
    }
  }
}

function handleShutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  console.log(`\n[shutdown] received ${signal}, stopping...`);

  servers.forEach((s) => s.close());
  if (pythonProcess) {
    pythonProcess.kill();
    // The engine gets a moment to exit cleanly before the process goes away.
    setTimeout(() => {
      if (pythonProcess) pythonProcess.kill('SIGKILL');
      process.exit(0);
    }, 2000).unref();
  } else {
    process.exit(0);
  }
}

process.on('SIGINT', () => handleShutdown('SIGINT'));
process.on('SIGTERM', () => handleShutdown('SIGTERM'));

startServer();
