/**
 * Lightweight session tokens.
 *
 * Login, signup and OTP verification only ever returned a `{ success, email }` message —
 * nothing the client could present back to prove it had authenticated. Every protected
 * route trusted whatever the client claimed (or nothing at all), so anyone could call
 * /api/optimize directly and spend LLM tokens without ever signing in. This issues a
 * signed, expiring bearer token on successful auth and verifies it on protected routes.
 *
 * Deliberately not a JWT library: the payload is one string and one signature, HMAC-
 * verified server-side, which is all a single-process session needs.
 */

const crypto = require('crypto');

const SESSION_TTL_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

// A secret that changes every restart still works — it invalidates existing sessions
// (users are asked to sign in again), it just never persists across deploys. Set
// SESSION_SECRET in .env for sessions that survive a restart.
let secret = process.env.SESSION_SECRET;
if (!secret) {
  secret = crypto.randomBytes(32).toString('hex');
  console.warn(
    '[sessions] SESSION_SECRET is not set — using a random secret for this process. ' +
    'Every restart will sign out all users. Set SESSION_SECRET in .env to persist sessions.',
  );
}

function base64url(buffer) {
  return buffer.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function sign(payload) {
  return base64url(crypto.createHmac('sha256', secret).update(payload).digest());
}

/** Mint a bearer token for an authenticated email. */
function createSessionToken(email) {
  const payload = JSON.stringify({ email: String(email).toLowerCase(), exp: Date.now() + SESSION_TTL_MS });
  const payloadB64 = base64url(Buffer.from(payload, 'utf8'));
  return `${payloadB64}.${sign(payloadB64)}`;
}

/** Verify a bearer token; returns { email } or null. */
function verifySessionToken(token) {
  if (typeof token !== 'string' || !token.includes('.')) return null;
  const [payloadB64, signature] = token.split('.');
  if (!payloadB64 || !signature) return null;

  const expectedSig = sign(payloadB64);
  const a = Buffer.from(signature);
  const b = Buffer.from(expectedSig);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;

  try {
    const payload = JSON.parse(Buffer.from(payloadB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8'));
    if (typeof payload.exp !== 'number' || Date.now() > payload.exp) return null;
    if (!payload.email) return null;
    return { email: payload.email };
  } catch {
    return null;
  }
}

/** Express middleware: requires a valid `Authorization: Bearer <token>` header. */
function requireAuth(req, res, next) {
  const header = req.headers.authorization || '';
  const [scheme, token] = header.split(' ');
  if (scheme !== 'Bearer' || !token) {
    return res.status(401).json({ error: 'Sign in to use this feature.' });
  }
  const session = verifySessionToken(token);
  if (!session) {
    return res.status(401).json({ error: 'Your session has expired. Please sign in again.' });
  }
  req.user = session;
  next();
}

module.exports = { createSessionToken, verifySessionToken, requireAuth };
