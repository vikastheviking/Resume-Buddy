/**
 * Turns the gap-keyword list from a dead end into a plan.
 *
 * The optimizer never fabricates a skill the candidate doesn't have — genuine gaps
 * stay gaps. This is the other half of that promise: a concrete way to actually close
 * them, so the next honest score is a higher one. Opt-in (a button, not automatic)
 * since it's a separate LLM call against the same shared daily budget as the rewrite.
 */

import { useState } from 'react';
import { getSkillGapPlan } from '../api';

export default function SkillGapPlan({ gapKeywords, jdText, onAuthError, onNotify }) {
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const skills = (gapKeywords ?? []).slice(0, 8);
  if (skills.length === 0) return null;

  const runPlan = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await getSkillGapPlan(jdText, skills);
      if (data.plan?.length) {
        setPlan(data.plan);
      } else {
        setError("Couldn't generate a plan right now — please try again in a moment.");
      }
    } catch (err) {
      if (onAuthError?.(err)) {
        // handled upstream (session prompt reopened)
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel skill-gap">
      <header className="panel-head">
        <div>
          <h2 className="display-heading">Close the gap</h2>
          <p className="prose-note">
            {skills.length} skill{skills.length === 1 ? '' : 's'} this job wants that your resume shows no
            evidence of — genuine gaps, not something a rewrite should invent. Here&rsquo;s how to actually
            close them.
          </p>
        </div>
        {!plan && (
          <button type="button" className="button button--ghost" onClick={runPlan} disabled={busy}>
            {busy ? 'Building plan…' : 'Get a skill-gap plan'}
          </button>
        )}
      </header>

      {error && <p className="alert is-error">{error}</p>}

      {plan && (
        <ul className="skill-gap-list">
          {plan.map((item) => (
            <li key={item.skill} className="skill-gap-card">
              <div className="skill-gap-card-head">
                <h3>{item.skill}</h3>
                {item.estimated_time && <span className="chip">{item.estimated_time}</span>}
              </div>
              {item.why_it_matters && <p className="prose-note">{item.why_it_matters}</p>}
              {item.how_to_close_it?.length > 0 && (
                <ul className="skill-gap-steps">
                  {item.how_to_close_it.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
