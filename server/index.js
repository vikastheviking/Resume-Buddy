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
const { verifyRealEmail } = require('./email-validator');
const { createAndSendOtp, verifyOtp } = require('./otp-service');
require('dotenv').config();

// Repo root: this file lives in server/, everything else resolves from one level up.
const ROOT_DIR = path.join(__dirname, '..');
const PYTHON_BIN = process.env.PYTHON_BIN || (process.platform === 'win32' ? 'py' : 'python');

const app = express();
const PORT = process.env.PORT || 3000;
const PYTHON_PORT = process.env.PYTHON_PORT || 5001;
const PYTHON_BASE_URL = `http://127.0.0.1:${PYTHON_PORT}`;
const IS_PRODUCTION = process.env.NODE_ENV === 'production';

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
      connectSrc: ["'self'"],
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

app.post('/api/auth/send-otp', authLimiter, async (req, res) => {
  try {
    const { email, mode = 'signup' } = req.body || {};
    if (!email) {
      return res.status(400).json({ success: false, error: 'Email address is required.' });
    }

    const verification = await verifyRealEmail(email);
    if (!verification.isValid) {
      return res.status(400).json({
        success: false,
        error: verification.error,
        suggestion: verification.suggestion,
      });
    }

    const cleanEmail = verification.cleanEmail || email.trim().toLowerCase();
    const otpResult = await createAndSendOtp(cleanEmail, mode === 'signin' ? 'signin' : 'signup');
    if (!otpResult.success) {
      return res.status(429).json(otpResult);
    }

    res.json({
      success: true,
      message: otpResult.message,
      email: cleanEmail,
      mode,
    });
  } catch (err) {
    return fail(res, 500, 'Could not send a verification code.', err, 'success');
  }
});

app.post('/api/auth/verify-otp', authLimiter, async (req, res) => {
  try {
    const { email, otp } = req.body || {};
    if (!email || !otp) {
      return res.status(400).json({ success: false, error: 'Both email and 6-digit verification code are required.' });
    }

    const verification = verifyOtp(email, otp);
    if (!verification.isValid) {
      return res.status(400).json({ success: false, error: verification.error });
    }

    // Register the address as a passwordless account. It deliberately has no usable
    // password: these users authenticate by OTP, and minting one with a shared literal
    // password would let anyone holding that string sign in as any of them.
    try {
      await engineFetch('/api/auth/ensure-user', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: verification.email }),
      });
    } catch (err) {
      console.error('[auth] could not persist OTP-verified user:', err.message);
    }

    res.json({
      success: true,
      message: 'Email successfully verified.',
      email: verification.email,
      mode: verification.mode,
    });
  } catch (err) {
    return fail(res, 500, 'Could not verify that code.', err, 'success');
  }
});

app.post('/api/auth/signup', authLimiter, async (req, res) => {
  try {
    const { email, password } = req.body || {};
    const verification = await verifyRealEmail(email);
    if (!verification.isValid) {
      return res.status(400).json({
        success: false,
        error: verification.error,
        suggestion: verification.suggestion,
      });
    }
    return await proxyJson(res, '/api/auth/signup', {
      email: verification.cleanEmail || email,
      password,
    }, { label: 'signup' });
  } catch (err) {
    return fail(res, 502, 'Could not create that account.', err, 'success');
  }
});

app.post('/api/auth/login', authLimiter, async (req, res) => {
  try {
    const { email, password } = req.body || {};
    return await proxyJson(res, '/api/auth/login', { email, password }, { label: 'login' });
  } catch (err) {
    return fail(res, 502, 'Could not sign you in.', err, 'success');
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

    const engineRes = await engineFetch('/api/extract', { method: 'POST', body: formData });
    const data = await engineRes.json();
    return res.status(engineRes.status).json(data);
  } catch (err) {
    if (isAbort(err)) {
      return fail(res, 504, 'Text extraction timed out. Try a smaller file.', err);
    }
    return fail(res, 502, 'Could not extract text from that file.', err);
  }
});

app.post('/api/optimize', optimizeLimiter, async (req, res) => {
  try {
    const { resume_text: resumeText, jd_text: jdText } = req.body || {};
    if (!resumeText || !jdText) {
      return res.status(400).json({ error: 'Both resume_text and jd_text are required.' });
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

/** PDF and DOCX exports differ only in route, media type and filename. */
function registerExport(route, enginePath, mediaType, filename) {
  app.post(route, async (req, res) => {
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
