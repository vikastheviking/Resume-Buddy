import { useCallback, useEffect, useRef, useState } from 'react';
import { downloadExport, getSample, optimize, scoreResume, setToken } from './api';
import { supabase } from './supabaseClient';
import { renderResumeMarkdown } from './markdown.jsx';
import AuditPanel from './components/AuditPanel';
import AuthDialog from './components/AuthDialog';
import DocumentInput from './components/DocumentInput';
import HistoryPanel from './components/HistoryPanel';
import ScorePanel from './components/ScorePanel';
import SkillGapPlan from './components/SkillGapPlan';

const THEME_STORAGE_KEY = 'resume_buddy_theme';

function readStoredTheme() {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY); // 'light' | 'dark' | null (follow system)
  } catch {
    return null;
  }
}

export default function App() {
  const [resumeText, setResumeText] = useState('');
  const [jdText, setJdText] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(null);
  const [loadingSample, setLoadingSample] = useState(false);
  const [user, setUser] = useState(null);
  const [userId, setUserId] = useState(null);
  const [authPrompt, setAuthPrompt] = useState(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [toast, setToast] = useState(null);
  const [theme, setTheme] = useState(readStoredTheme);
  const [quickScore, setQuickScore] = useState(null);
  const [checkingScore, setCheckingScore] = useState(false);

  const resultsRef = useRef(null);
  const toastTimer = useRef(0);

  const notify = useCallback((message) => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  }, []);

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  useEffect(() => {
    if (theme) document.documentElement.setAttribute('data-theme', theme);
    else document.documentElement.removeAttribute('data-theme');
  }, [theme]);

  const toggleTheme = () => {
    const systemPrefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    const current = theme || (systemPrefersDark ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      /* per-viewer preference only */
    }
  };

  // Supabase persists its own session (with auto-refresh) under its own localStorage
  // key, so this reads the real, current session on load instead of just assuming a
  // previously-remembered email/token pair is still valid - and onAuthStateChange
  // keeps user/token in sync afterwards (token refresh, sign-out in another tab, etc.).
  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      if (data.session) {
        setUser(data.session.user.email);
        setUserId(data.session.user.id);
        setToken(data.session.access_token);
      }
    });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session ? session.user.email : null);
      setUserId(session ? session.user.id : null);
      setToken(session ? session.access_token : null);
    });

    return () => subscription.subscription.unsubscribe();
  }, []);

  const signIn = useCallback((email, token, id) => {
    setUser(email);
    setUserId(id || null);
    setToken(token || null);
    setAuthOpen(false);
    setAuthPrompt(null);
  }, []);

  const signOut = async () => {
    await supabase.auth.signOut();
    setUser(null);
    setUserId(null);
    setToken(null);
    notify('Signed out.');
  };

  const loadSample = async () => {
    setLoadingSample(true);
    try {
      const data = await getSample();
      setResumeText(data.resume);
      setJdText(data.jd);
      notify(`Loaded the “${data.profile_name}” example.`);
    } catch (error) {
      notify(error.message);
    } finally {
      setLoadingSample(false);
    }
  };

  /** True (and prompts sign-in again) when `error` is the server rejecting a missing/expired session. */
  const recoverFromAuthError = useCallback(
    (error) => {
      if (!/session has expired|sign in to use/i.test(error.message)) return false;
      supabase.auth.signOut();
      setUser(null);
      setToken(null);
      setAuthPrompt('Your session expired. Please sign in again to continue.');
      setAuthOpen(true);
      return true;
    },
    [],
  );

  const checkScore = async () => {
    if (!resumeText.trim() || !jdText.trim()) {
      notify('Add both a resume and a job description first.');
      return;
    }
    setCheckingScore(true);
    try {
      const data = await scoreResume(resumeText, jdText);
      setQuickScore(data.overall_score);
    } catch (error) {
      notify(error.message);
    } finally {
      setCheckingScore(false);
    }
  };

  const runOptimization = async () => {
    if (!user) {
      setAuthPrompt('Sign in or continue as a guest to optimize your resume.');
      setAuthOpen(true);
      return;
    }
    if (!resumeText.trim() || !jdText.trim()) {
      notify('Add both a resume and a job description first.');
      return;
    }

    setBusy(true);
    try {
      const data = await optimize(resumeText, jdText);
      setResult(data);
      const delta = data.updated_score - data.actual_score;
      notify(
        delta > 0
          ? `Rewritten. ATS score ${data.actual_score}% → ${data.updated_score}%.`
          : `Rewritten. ATS score is ${data.updated_score}%.`,
      );
      requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));

      // Best-effort history save, written directly to Supabase with the user's own
      // session (RLS scopes it to their own rows) - a save failure (network blip,
      // guest session with no history access, whatever) must never block the result
      // the user is already looking at.
      if (userId) {
        supabase
          .from('resumes')
          .insert({
            user_id: userId,
            jd_text: jdText,
            optimized_resume: data.optimized_resume,
            actual_score: data.actual_score,
            updated_score: data.updated_score,
            parsed_data: data.optimized_audit,
            status: 'completed',
          })
          .then(({ error }) => {
            if (error) console.error('[history] could not save this optimization:', error.message);
          });
      }
    } catch (error) {
      if (!recoverFromAuthError(error)) notify(error.message);
    } finally {
      setBusy(false);
    }
  };

  const loadFromHistory = (row) => {
    setJdText(row.jd_text || '');
    setResult({
      actual_score: row.actual_score,
      updated_score: row.updated_score,
      optimized_resume: row.optimized_resume,
      optimized_audit: row.parsed_data || {},
    });
    setHistoryOpen(false);
    requestAnimationFrame(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  const copyResume = async () => {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(result.optimized_resume);
      notify('Copied to clipboard.');
    } catch {
      notify('Your browser blocked clipboard access.');
    }
  };

  const runExport = async (format) => {
    if (!result) return;
    setExporting(format);
    try {
      await downloadExport(format, result.optimized_resume);
      notify(`${format.toUpperCase()} downloaded.`);
    } catch (error) {
      if (!recoverFromAuthError(error)) notify(error.message);
    } finally {
      setExporting(null);
    }
  };

  return (
    <>
      <header className="masthead">
        <div className="shell masthead-inner">
          <div className="brand">
            <span className="brand-mark">RB</span>
            <span className="brand-name">Resume&nbsp;Buddy</span>
            <span className="brand-rule" aria-hidden="true" />
            <span className="brand-tagline">ATS Resume Optimizer</span>
          </div>

          <nav className="masthead-actions">
            <button
              type="button"
              className="button button--ghost"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              {theme === 'dark' ? 'Light mode' : 'Dark mode'}
            </button>
            <button type="button" className="button button--ghost" onClick={loadSample} disabled={loadingSample}>
              {loadingSample ? 'Loading…' : 'Load example'}
            </button>
            {user && (
              <button type="button" className="button button--ghost" onClick={() => setHistoryOpen(true)}>
                History
              </button>
            )}
            {user ? (
              <span className="identity">
                <span className="identity-email" title={user}>
                  {user}
                </span>
                <button type="button" className="link-button" onClick={signOut}>
                  Sign out
                </button>
              </span>
            ) : (
              <button
                type="button"
                className="button button--primary"
                onClick={() => {
                  setAuthPrompt(null);
                  setAuthOpen(true);
                }}
              >
                Sign in
              </button>
            )}
          </nav>
        </div>
      </header>

      <main className="shell">
        <section className="intro">
          <h1 className="display-heading intro-title">
            Rewrite your resume for the job you actually want.
          </h1>
          <p className="intro-lead">
            Paste your resume and a target job description. Resume&nbsp;Buddy rewrites it into a
            clean, single-column format that applicant tracking systems can read — and scores the
            result honestly, without inventing a word of experience you don&rsquo;t have.
          </p>
        </section>

        <div className="inputs">
          <DocumentInput
            ordinal="I"
            label="Your resume"
            hint="PDF, DOCX or TXT"
            placeholder="Paste your resume here, or upload a file above…"
            value={resumeText}
            onChange={setResumeText}
            onNotify={notify}
          />
          <DocumentInput
            ordinal="II"
            label="Target job description"
            hint="PDF, DOCX or TXT"
            placeholder="Paste the job description here, or upload a file above…"
            value={jdText}
            onChange={setJdText}
            onNotify={notify}
          />
        </div>

        <div className="action">
          <div className="action-buttons">
            <button
              type="button"
              className="button button--ghost"
              onClick={checkScore}
              disabled={checkingScore || busy}
            >
              {checkingScore ? 'Checking…' : 'Check score'}
            </button>
            <button type="button" className="button button--primary button--large" onClick={runOptimization} disabled={busy}>
              {busy ? 'Optimizing…' : 'Optimize resume'}
            </button>
          </div>
          {quickScore !== null && !busy && !result && (
            <p className="action-note" role="status">
              Baseline match: <strong>{quickScore}%</strong> — sign in and optimize to close the gap.
            </p>
          )}
          {busy && (
            <p className="action-note" role="status">
              Extracting keywords, rewriting bullets and scoring alignment. This can take up to a minute.
            </p>
          )}
        </div>

        {result && (
          <div className="results" ref={resultsRef}>
            <ScorePanel actual={result.actual_score} updated={result.updated_score} />

            <section className="panel sheet-panel">
              <header className="panel-head panel-head--split">
                <div>
                  <h2 className="display-heading">Rewritten resume</h2>
                  <p className="prose-note">
                    Single-column and ATS-parseable, with your contact details and history preserved.
                  </p>
                </div>
                <div className="toolbar">
                  <button type="button" className="button button--ghost" onClick={copyResume}>
                    Copy text
                  </button>
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => runExport('pdf')}
                    disabled={exporting === 'pdf'}
                  >
                    {exporting === 'pdf' ? 'Generating…' : 'Download PDF'}
                  </button>
                  <button
                    type="button"
                    className="button button--ghost"
                    onClick={() => runExport('docx')}
                    disabled={exporting === 'docx'}
                  >
                    {exporting === 'docx' ? 'Generating…' : 'Download DOCX'}
                  </button>
                </div>
              </header>

              <AuditPanel audit={result.optimized_audit} />

              <article className="sheet">{renderResumeMarkdown(result.optimized_resume)}</article>
            </section>

            <SkillGapPlan
              gapKeywords={result.optimized_audit.gap_keywords}
              jdText={jdText}
              onAuthError={recoverFromAuthError}
              onNotify={notify}
            />
          </div>
        )}
      </main>

      <footer className="colophon">
        <div className="shell">
          <p>
            Scores are measured, never targeted. Nothing is added to your resume that you did not
            write.
          </p>
        </div>
      </footer>

      <AuthDialog
        open={authOpen}
        prompt={authPrompt}
        onClose={() => setAuthOpen(false)}
        onAuthenticated={signIn}
        onNotify={notify}
      />

      <HistoryPanel
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        onSelect={loadFromHistory}
        onNotify={notify}
      />

      {toast && (
        <div className="toast" role="status" aria-live="polite">
          {toast}
        </div>
      )}
    </>
  );
}
