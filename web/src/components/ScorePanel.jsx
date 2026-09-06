import { useEffect, useRef, useState } from 'react';

/** Count from 0 to `target`, easing out. Respects reduced-motion preferences. */
function useCountUp(target, duration = 900) {
  const [value, setValue] = useState(0);
  const frameRef = useRef(0);

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      setValue(target);
      return undefined;
    }

    const start = performance.now();
    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - (1 - progress) ** 2;
      setValue(Math.round(eased * target));
      if (progress < 1) frameRef.current = requestAnimationFrame(tick);
    };
    frameRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frameRef.current);
  }, [target, duration]);

  return value;
}

function Reading({ caption, score, note, variant }) {
  const shown = useCountUp(score);
  return (
    <div className={`reading reading--${variant}`}>
      <p className="label">{caption}</p>
      <p className="reading-value">
        {shown}
        <span className="reading-unit">%</span>
      </p>
      <div className="meter" role="img" aria-label={`${caption}: ${score} percent`}>
        <span className="meter-fill" style={{ width: `${score}%` }} />
      </div>
      <p className="reading-note">{note}</p>
    </div>
  );
}

/**
 * The before/after comparison.
 *
 * The middle column reports the movement exactly as measured, including no change and
 * regressions — a rewrite that does not help should not look like one that does.
 */
export default function ScorePanel({ actual, updated }) {
  const delta = updated - actual;
  const tone = delta > 0 ? 'up' : delta < 0 ? 'down' : 'flat';
  const deltaLabel = delta > 0 ? `+${delta}` : delta < 0 ? `${delta}` : 'No change';

  return (
    <section className="scores">
      <header className="scores-head">
        <h2 className="display-heading">ATS Compatibility</h2>
        <p className="prose-note">
          Measured against the job description: keyword coverage, semantic alignment,
          quantified impact and formatting.
        </p>
      </header>

      <div className="scores-grid">
        <Reading caption="Original" score={actual} note="Your resume as submitted" variant="before" />

        <div className={`delta delta--${tone}`}>
          <span className="delta-value">{deltaLabel}</span>
          {delta !== 0 && <span className="delta-unit">points</span>}
        </div>

        <Reading caption="Rewritten" score={updated} note="After optimization" variant="after" />
      </div>
    </section>
  );
}
