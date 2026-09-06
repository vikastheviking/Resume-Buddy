/**
 * One-Time Passcode (OTP) Email Authentication Service.
 * Implements cryptographically secure 6-digit verification codes,
 * rate limiting, automated email dispatch via Nodemailer, and dev fallbacks.
 */

const crypto = require('crypto');
const nodemailer = require('nodemailer');
require('dotenv').config();

// In-memory OTP store: email -> { otp, expiresAt, attempts, lastSentAt, mode }
//
// Single-process only: codes issued by one instance are unknown to another, so running
// more than one replica needs a shared store (Redis) instead.
const otpStore = new Map();

const OTP_TTL_MS = 10 * 60 * 1000;
const RESEND_COOLDOWN_MS = 45 * 1000;
const MAX_ATTEMPTS = 5;
const MAX_PENDING_CODES = 10000;
const SWEEP_INTERVAL_MS = 5 * 60 * 1000;

/**
 * Drop expired codes.
 *
 * Entries were previously only removed when someone tried to use them, so codes that
 * were requested and abandoned accumulated for the lifetime of the process.
 */
function sweepExpiredOtps(now = Date.now()) {
  let removed = 0;
  for (const [email, record] of otpStore) {
    if (now > record.expiresAt) {
      otpStore.delete(email);
      removed += 1;
    }
  }
  return removed;
}

const sweepTimer = setInterval(sweepExpiredOtps, SWEEP_INTERVAL_MS);
sweepTimer.unref(); // never hold the process open just for the sweep

// 1. SMTP Transporter Configuration
let transporter = null;

function getTransporter() {
  if (transporter) return transporter;

  // 1. Gmail App Password (Direct from user's Gmail)
  const gmailUser = process.env.GMAIL_USER || (process.env.SMTP_USER && process.env.SMTP_USER.includes('@gmail.com') ? process.env.SMTP_USER : null);
  const gmailPass = process.env.GMAIL_APP_PASSWORD || (gmailUser ? process.env.SMTP_PASS : null);

  if (gmailUser && gmailPass) {
    const cleanPass = gmailPass.replace(/\s+/g, '');
    transporter = nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: gmailUser,
        pass: cleanPass
      }
    });
    console.log(`[OTP Service] Configured live Gmail SMTP sender: ${gmailUser}`);
    return transporter;
  }

  // 2. Generic SMTP (Brevo, Resend, SendGrid, Amazon SES, Custom SMTP)
  const host = process.env.SMTP_HOST;
  const port = parseInt(process.env.SMTP_PORT || '587', 10);
  const user = process.env.SMTP_USER;
  const pass = process.env.SMTP_PASS;

  if (host && user && pass) {
    transporter = nodemailer.createTransport({
      host,
      port,
      secure: port === 465,
      auth: { user, pass }
    });
    console.log(`[OTP Service] Configured live custom SMTP transport with host: ${host}`);
    return transporter;
  }

  return null;
}

/**
 * Sends professional branded HTML email with the 6-digit OTP code.
 */
async function sendOtpEmail(email, otp, mode = 'signup') {
  const mailer = getTransporter();
  const title = mode === 'signup' ? 'Complete Your Registration' : 'Sign In to Your Account';

  const htmlContent = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; }
        .container { max-width: 520px; margin: 40px auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
        .header { background: linear-gradient(135deg, #1e40af 0%, #3b82f6 100%); padding: 32px 24px; text-align: center; color: #ffffff; }
        .title { font-size: 24px; font-weight: 800; margin: 0; }
        .content { padding: 36px 32px; text-align: center; color: #1e293b; }
        .greeting { font-size: 16px; margin-bottom: 20px; line-height: 1.5; }
        .otp-box { background: #f0fdf4; border: 2px dashed #86efac; border-radius: 12px; padding: 20px; margin: 28px 0; }
        .otp-code { font-size: 38px; font-weight: 800; letter-spacing: 8px; color: #15803d; font-family: 'Courier New', monospace; }
        .notice { font-size: 13px; color: #64748b; line-height: 1.5; margin-top: 24px; }
        .footer { background: #f8fafc; padding: 20px; text-align: center; font-size: 12px; color: #94a3b8; border-top: 1px solid #e2e8f0; }
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1 class="title">🎯 ATS Resume Architect</h1>
        </div>
        <div class="content">
          <p class="greeting"><strong>${title}</strong><br>Use the 6-digit verification code below to confirm your email:</p>
          <div class="otp-box">
            <div class="otp-code">${otp}</div>
          </div>
          <p class="notice">This code is valid for <strong>10 minutes</strong>. If you did not request this verification, you can safely ignore this email.</p>
        </div>
        <div class="footer">
          ATS Resume Architect &bull; Automated Security Service &bull; Zero-Spam Guarantee
        </div>
      </div>
    </body>
    </html>
  `;

  if (mailer) {
    const senderEmail = process.env.GMAIL_USER || process.env.SMTP_USER;
    const fromAddress = process.env.SMTP_FROM || (senderEmail ? `"ATS Resume Architect" <${senderEmail}>` : '"ATS Architect" <auth@ats-architect.com>');
    try {
      await mailer.sendMail({
        from: fromAddress,
        to: email,
        subject: `🎯 Your Verification Code: ${otp}`,
        text: `Your ATS Resume Architect verification code is: ${otp}. It expires in 10 minutes.`,
        html: htmlContent
      });
      console.log(`[OTP Service] Successfully dispatched real email to ${email}`);
      return { sent: true, mode: 'live_email' };
    } catch (err) {
      console.error(`[OTP Service] Failed to send via SMTP:`, err.message);
    }
  }

  // Development Fallback: Log strictly to backend console (never returned to browser)
  console.log(`\n========================================================`);
  console.log(`📨 [OTP DISPATCHED - BACKEND TERMINAL LOG]`);
  console.log(`To:        ${email}`);
  console.log(`Action:    ${title}`);
  console.log(`Code:      ${otp}`);
  console.log(`Valid:     10 minutes`);
  console.log(`(Configure GMAIL_USER & GMAIL_APP_PASSWORD in .env for live inbox delivery)`);
  console.log(`========================================================\n`);

  return { sent: true, mode: 'terminal_dev' };
}

/**
 * Creates and dispatches a 6-digit OTP for the given email.
 */
async function createAndSendOtp(email, mode = 'signup') {
  const cleanEmail = email.trim().toLowerCase();
  const existing = otpStore.get(cleanEmail);

  // Per-address cooldown. This cannot bound an attacker cycling through many different
  // addresses, which is why the HTTP layer also rate-limits by client IP.
  const now = Date.now();
  if (existing && (now - existing.lastSentAt) < RESEND_COOLDOWN_MS) {
    const waitSeconds = Math.ceil((RESEND_COOLDOWN_MS - (now - existing.lastSentAt)) / 1000);
    return {
      success: false,
      error: `Please wait ${waitSeconds} seconds before requesting a new verification code.`,
      cooldown: waitSeconds
    };
  }

  if (otpStore.size >= MAX_PENDING_CODES) {
    sweepExpiredOtps(now);
    if (otpStore.size >= MAX_PENDING_CODES) {
      return {
        success: false,
        error: 'The verification service is busy. Please try again in a few minutes.'
      };
    }
  }

  // Cryptographically secure 6-digit code. randomInt's upper bound is exclusive, so the
  // ceiling is 1000000 for the range to actually include 999999.
  const otp = String(crypto.randomInt(100000, 1000000));
  const expiresAt = now + OTP_TTL_MS;

  otpStore.set(cleanEmail, {
    otp,
    expiresAt,
    attempts: 0,
    lastSentAt: now,
    mode
  });

  const sendResult = await sendOtpEmail(cleanEmail, otp, mode);

  return {
    success: true,
    message: sendResult.mode === 'live_email'
      ? `Verification code sent to ${cleanEmail}. Please check your inbox!`
      : `Verification code sent to ${cleanEmail}. Check your inbox!`,
    expiresIn: 600,
    mode: sendResult.mode
  };
}

/**
 * Verifies an entered OTP code against the store.
 */
function verifyOtp(email, inputOtp) {
  const cleanEmail = email.trim().toLowerCase();
  const record = otpStore.get(cleanEmail);

  if (!record) {
    return {
      isValid: false,
      error: 'No active verification code found for this email. Please request a new code.'
    };
  }

  if (Date.now() > record.expiresAt) {
    otpStore.delete(cleanEmail);
    return {
      isValid: false,
      error: 'Your verification code has expired. Please request a new one.'
    };
  }

  if (record.attempts >= MAX_ATTEMPTS) {
    otpStore.delete(cleanEmail);
    return {
      isValid: false,
      error: 'Too many incorrect attempts. Please request a new verification code.'
    };
  }

  // Constant-time comparison. timingSafeEqual throws on a length mismatch, and a 6-
  // character input can still be more than 6 bytes (full-width digits, emoji), so the
  // byte lengths are compared before handing the buffers over.
  const cleanInput = String(inputOtp).trim();
  const expected = Buffer.from(record.otp, 'utf8');
  const supplied = Buffer.from(cleanInput, 'utf8');
  const isMatch = expected.length === supplied.length && crypto.timingSafeEqual(expected, supplied);

  if (!isMatch) {
    record.attempts += 1;
    const remaining = MAX_ATTEMPTS - record.attempts;
    return {
      isValid: false,
      error: `Incorrect verification code. ${remaining} attempt(s) remaining.`
    };
  }

  // Valid OTP!
  const mode = record.mode;
  otpStore.delete(cleanEmail); // One-time use: consume immediately

  return {
    isValid: true,
    email: cleanEmail,
    mode
  };
}

module.exports = {
  createAndSendOtp,
  verifyOtp,
  sendOtpEmail
};
