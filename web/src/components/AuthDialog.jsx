import { useCallback, useEffect, useRef, useState } from 'react';
import { sendOtp, validateEmail, verifyOtp } from '../api';

const RESEND_SECONDS = 45;
const GUEST_IDENTITY = 'guest@resume-buddy.local';

/**
 * Two-step email authentication: request a one-time code, then enter it.
 *
 * The email field validates as you type (debounced) against the server's deliverability
 * check, so a typo is caught before a code is sent to an address that cannot receive it.
 */
export default function AuthDialog({ open, prompt, onClose, onAuthenticated, onNotify }) {
  const [mode, setMode] = useState('login');
  const [step, setStep] = useState('email');
  const [email, setEmail] = useState('');
  const [otp, setOtp] = useState('');
  const [pendingEmail, setPendingEmail] = useState('');
  const [hint, setHint] = useState(null); // { tone, message, fix? }
  const [alert, setAlert] = useState(null);
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  const emailRef = useRef(null);
  const otpRef = useRef(null);

  // Reset to a clean state whenever the dialog is opened.
  useEffect(() => {
    if (!open) return;
    setStep('email');
    setOtp('');
    setHint(null);
    setAlert(prompt ? { tone: 'error', message: prompt } : null);
    const focus = setTimeout(() => emailRef.current?.focus(), 60);
    return () => clearTimeout(focus);
  }, [open, prompt]);

  // Resend cooldown.
  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const timer = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  // Close on Escape.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  // Debounced deliverability check.
  useEffect(() => {
    const candidate = email.trim();
    if (!open || step !== 'email' || !candidate) {
      setHint(null);
      return undefined;
    }
    if (!candidate.includes('@') || candidate.length < 5) {
      setHint({ tone: 'neutral', message: 'Enter a complete address, e.g. name@company.com' });
      return undefined;
    }

    setHint({ tone: 'neutral', message: 'Checking mail server…' });
    const timer = setTimeout(async () => {
      try {
        const data = await validateEmail(candidate);
        if (data.isValid) {
          setHint({ tone: 'ok', message: 'Deliverable address' });
        } else if (data.suggestion) {
          const [local] = candidate.split('@');
          setHint({
            tone: 'warn',
            message: `Did you mean @${data.suggestion}?`,
            fix: `${local}@${data.suggestion}`,
          });
        } else {
          setHint({ tone: 'error', message: data.error || 'That address could not be verified.' });
        }
      } catch {
        setHint(null); // network hiccup: stay quiet rather than blocking the user
      }
    }, 450);

    return () => clearTimeout(timer);
  }, [email, open, step]);

  const requestCode = useCallback(
    async (target, { resend = false } = {}) => {
      setBusy(true);
      setAlert(null);
      try {
        const data = await sendOtp(target, mode);
        setPendingEmail(data.email || target);
        setStep('otp');
        setCooldown(RESEND_SECONDS);
        setTimeout(() => otpRef.current?.focus(), 60);
        onNotify(resend ? 'A new verification code is on its way.' : data.message);
      } catch (error) {
        const suggestion = error.payload?.suggestion;
        setAlert({
          tone: 'error',
          message: suggestion ? `${error.message} Did you mean @${suggestion}?` : error.message,
        });
      } finally {
        setBusy(false);
      }
    },
    [mode, onNotify],
  );

  if (!open) return null;

  const submitEmail = (event) => {
    event.preventDefault();
    const candidate = email.trim();
    if (!candidate) {
      setAlert({ tone: 'error', message: 'Enter your email address.' });
      return;
    }
    requestCode(candidate);
  };

  const submitOtp = async (event) => {
    event.preventDefault();
    if (otp.trim().length !== 6) {
      setAlert({ tone: 'error', message: 'Enter the complete six-digit code.' });
      return;
    }
    setBusy(true);
    setAlert(null);
    try {
      const data = await verifyOtp(pendingEmail, otp.trim());
      onAuthenticated(data.email);
      onNotify(`Signed in as ${data.email}`);
    } catch (error) {
      setAlert({ tone: 'error', message: error.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="auth-heading">
        <header className="dialog-head">
          <div>
            <p className="label">Resume-Buddy</p>
            <h2 id="auth-heading" className="display-heading dialog-heading">
              {step === 'otp' ? 'Enter your code' : mode === 'signup' ? 'Create an account' : 'Sign in'}
            </h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </header>

        {alert && <p className={`alert is-${alert.tone}`}>{alert.message}</p>}

        {step === 'email' ? (
          <>
            <div className="tabs" role="tablist">
              {[
                ['login', 'Sign in'],
                ['signup', 'Create account'],
              ].map(([key, text]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={mode === key}
                  className={`tab${mode === key ? ' is-active' : ''}`}
                  onClick={() => {
                    setMode(key);
                    setAlert(null);
                  }}
                >
                  {text}
                </button>
              ))}
            </div>

            <form className="form" onSubmit={submitEmail}>
              <label className="label" htmlFor="auth-email">
                Email address
              </label>
              <input
                id="auth-email"
                ref={emailRef}
                className="field"
                type="email"
                autoComplete="email"
                placeholder="name@company.com"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
              {hint && (
                <p className={`hint is-${hint.tone}`}>
                  {hint.message}
                  {hint.fix && (
                    <button type="button" className="link-button" onClick={() => setEmail(hint.fix)}>
                      Use it
                    </button>
                  )}
                </p>
              )}

              <button type="submit" className="button button--primary button--block" disabled={busy}>
                {busy ? 'Sending…' : 'Email me a code'}
              </button>
            </form>

            <div className="rule-label">
              <span>or</span>
            </div>

            <button
              type="button"
              className="button button--ghost button--block"
              onClick={() => {
                onAuthenticated(GUEST_IDENTITY);
                onNotify('Continuing as a guest.');
              }}
            >
              Continue as guest
            </button>
          </>
        ) : (
          <>
            <p className="prose-note">
              We sent a six-digit code to <strong>{pendingEmail}</strong>.
            </p>

            <form className="form" onSubmit={submitOtp}>
              <label className="sr-only" htmlFor="auth-otp">
                Six-digit verification code
              </label>
              <input
                id="auth-otp"
                ref={otpRef}
                className="field field--code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="000000"
                value={otp}
                onChange={(event) => setOtp(event.target.value.replace(/\D/g, ''))}
                required
              />
              <button type="submit" className="button button--primary button--block" disabled={busy}>
                {busy ? 'Verifying…' : 'Verify and continue'}
              </button>
            </form>

            <div className="dialog-foot">
              <button
                type="button"
                className="link-button"
                onClick={() => {
                  setStep('email');
                  setAlert(null);
                }}
              >
                Use a different address
              </button>
              <button
                type="button"
                className="link-button"
                disabled={cooldown > 0 || busy}
                onClick={() => requestCode(pendingEmail, { resend: true })}
              >
                {cooldown > 0 ? `Resend in ${cooldown}s` : 'Resend code'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
