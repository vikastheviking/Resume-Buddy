import { useCallback, useEffect, useRef, useState } from 'react';
import { checkAvailability, validateEmail } from '../api';
import { supabase } from '../supabaseClient';

const RESEND_SECONDS = 45;
const GUEST_IDENTITY = 'guest@resume-buddy.local';
const PHONE_PATTERN = /^[+\d][\d\s\-()]{6,19}$/;
// Supabase's OTP length isn't guaranteed to be 6 digits (depends on project config),
// so this only checks it looks like a numeric code and lets Supabase's own
// verification be the source of truth on whether it's actually correct.
const OTP_PATTERN = /^\d{4,12}$/;

/**
 * Two-step email authentication via Supabase Auth: request a one-time code, then enter
 * it. Supabase sends and verifies the code itself; this dialog only decides which of
 * Sign In / Create Account the user meant (via the availability check below) before
 * asking Supabase to send one.
 *
 * The email field validates as you type (debounced) against the server's deliverability
 * check, so a typo is caught before a code is sent to an address that cannot receive it.
 */
export default function AuthDialog({ open, prompt, onClose, onAuthenticated, onNotify }) {
  const [mode, setMode] = useState('login');
  const [step, setStep] = useState('email');
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [phone, setPhone] = useState('');
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
        const isSignup = mode === 'signup';
        const cleanPhone = phone.trim();
        const cleanName = fullName.trim();

        // Sign In vs Create Account is enforced here, before Supabase ever sends a
        // code: Sign In requires the account to already exist, Create Account
        // requires the email (and phone) to be free.
        const availability = await checkAvailability(target, isSignup ? cleanPhone : undefined);
        if (!isSignup && !availability.emailExists) {
          throw new Error('No account found with this email. Please create an account instead.');
        }
        if (isSignup && availability.emailExists) {
          throw new Error('An account with this email already exists. Please sign in instead.');
        }
        if (isSignup && availability.phoneExists) {
          throw new Error('This phone number is already registered to another account.');
        }

        const { error } = await supabase.auth.signInWithOtp({
          email: target,
          options: {
            shouldCreateUser: isSignup,
            ...(isSignup ? { data: { full_name: cleanName, phone: cleanPhone } } : {}),
          },
        });
        if (error) throw error;

        setPendingEmail(target);
        setStep('otp');
        setCooldown(RESEND_SECONDS);
        setTimeout(() => otpRef.current?.focus(), 60);
        onNotify(resend ? 'A new verification code is on its way.' : 'Verification code sent to your email!');
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
    [mode, fullName, phone, onNotify],
  );

  if (!open) return null;

  const submitEmail = (event) => {
    event.preventDefault();
    const candidate = email.trim();
    if (!candidate) {
      setAlert({ tone: 'error', message: 'Enter your email address.' });
      return;
    }
    if (mode === 'signup') {
      if (!fullName.trim()) {
        setAlert({ tone: 'error', message: 'Enter your full name.' });
        return;
      }
      if (!PHONE_PATTERN.test(phone.trim())) {
        setAlert({ tone: 'error', message: 'Enter a valid phone number.' });
        return;
      }
    }
    requestCode(candidate);
  };

  const submitOtp = async (event) => {
    event.preventDefault();
    const cleanOtp = otp.trim();
    if (!OTP_PATTERN.test(cleanOtp)) {
      setAlert({ tone: 'error', message: 'Enter the verification code from your email.' });
      return;
    }
    setBusy(true);
    setAlert(null);
    try {
      const { data, error } = await supabase.auth.verifyOtp({
        email: pendingEmail,
        token: cleanOtp,
        type: 'email',
      });
      if (error || !data.session) {
        throw new Error(error?.message || 'Invalid or expired code.');
      }
      onAuthenticated(data.user.email, data.session.access_token, data.user.id);
      onNotify(`Signed in as ${data.user.email}`);
    } catch (error) {
      setAlert({ tone: 'error', message: error.message });
    } finally {
      setBusy(false);
    }
  };

  const continueAsGuest = async () => {
    setBusy(true);
    setAlert(null);
    try {
      const { data, error } = await supabase.auth.signInAnonymously();
      if (error) throw error;
      onAuthenticated(data.user?.email || GUEST_IDENTITY, data.session.access_token, data.user?.id);
      onNotify('Continuing as a guest.');
    } catch (error) {
      setAlert({
        tone: 'error',
        message: /anonymous/i.test(error.message)
          ? 'Guest access is not enabled for this project yet.'
          : error.message,
      });
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
              {mode === 'signup' && (
                <>
                  <label className="label" htmlFor="auth-name">
                    Full name
                  </label>
                  <input
                    id="auth-name"
                    className="field"
                    type="text"
                    autoComplete="name"
                    placeholder="Jane Doe"
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    required
                  />

                  <label className="label" htmlFor="auth-phone">
                    Phone number
                  </label>
                  <input
                    id="auth-phone"
                    className="field"
                    type="tel"
                    autoComplete="tel"
                    placeholder="+1 555 123 4567"
                    value={phone}
                    onChange={(event) => setPhone(event.target.value)}
                    required
                  />
                </>
              )}

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
              disabled={busy}
              onClick={continueAsGuest}
            >
              Continue as guest
            </button>
          </>
        ) : (
          <>
            <p className="prose-note">
              We sent a verification code to <strong>{pendingEmail}</strong>.
            </p>
            <p className="prose-note" style={{ fontSize: '0.85em' }}>
              Don&rsquo;t see it? Check your spam/junk folder.
            </p>

            <form className="form" onSubmit={submitOtp}>
              <label className="sr-only" htmlFor="auth-otp">
                Verification code
              </label>
              <input
                id="auth-otp"
                ref={otpRef}
                className="field field--code"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={12}
                placeholder="Enter code"
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
