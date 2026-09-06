import { useCallback, useEffect, useRef, useState } from 'react';
import { downloadExport, getSample, optimize } from './api';
import { renderResumeMarkdown } from './markdown.jsx';
import AuditPanel from './components/AuditPanel';
import AuthDialog from './components/AuthDialog';
import DocumentInput from './components/DocumentInput';
import ScorePanel from './components/ScorePanel';

const AUTH_STORAGE_KEY = 'resume_buddy_user';

function readStoredUser() {
  try {
    return localStorage.getItem(AUTH_STORAGE_KEY);
  } catch {
    return null; // private browsing, or site data blocked
  }
}

export default function App() {
  const [resumeText, setResumeText] = useState('');
  const [jdText, setJdText] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(null);
  const [loadingSample, setLoadingSample] = useState(false);
  const [user, setUser] = useState(readStoredUser);
  const [authPrompt, setAuthPrompt] = useState(null);
  const [authOpen, setAuthOpen] = useState(false);
  const [toast, setToast] = useState(null);

  const resultsRef = useRef(null);
  const toastTimer = useRef(0);

  const notify = useCallback((message) => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 4000);
  }, []);

  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const signIn = useCallback(
    (email) => {
      setUser(email);
      try {
        localStorage.setItem(AUTH_STORAGE_KEY, email);
      } catch {
        /* session-only sign-in is an acceptable fallback */
      }
      setAuthOpen(false);
      setAuthPrompt(null);
    },
    [],
  );

  const signOut = () => {
    setUser(null);
    try {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    } catch {
      /* nothing to clear */
    }
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
    } catch (error) {
      notify(error.message);
    } finally {
      setBusy(false);
    }
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
      notify(error.message);
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
            <button type="button" className="button button--ghost" onClick={loadSample} disabled={loadingSample}>
              {loadingSample ? 'Loading…' : 'Load example'}
            </button>
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
          <button type="button" className="button button--primary button--large" onClick={runOptimization} disabled={busy}>
            {busy ? 'Optimizing…' : 'Optimize resume'}
          </button>
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

      {toast && (
        <div className="toast" role="status" aria-live="polite">
          {toast}
        </div>
      )}
    </>
  );
}
