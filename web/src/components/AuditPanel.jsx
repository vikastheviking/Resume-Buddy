/**
 * The evidence behind the score.
 *
 * A bare number asks to be taken on trust. This breaks it into its components, names the
 * job-description terms the rewrite actually picked up, and says plainly when only a
 * formatting pass ran so a structural result is never mistaken for an AI rewrite.
 */

function Row({ term, children }) {
  return (
    <div className="audit-row">
      <dt className="label">{term}</dt>
      <dd>{children}</dd>
    </div>
  );
}

export default function AuditPanel({ audit }) {
  if (!audit) return null;

  const injected = audit.injected_keywords ?? [];
  const alerts = audit.format_alerts ?? [];
  const writingTips = audit.writing_tips ?? [];

  const components = [
    ['Keywords', audit.keyword_score],
    ['Semantic', audit.semantic_score],
    ['Impact', audit.impact_score],
    ['Format', audit.format_score],
  ];

  // rewrite_status names *why* engine_used is what it is, so the notice below is never
  // misleading — a rewrite that ran successfully but honestly scored worse than the
  // original (status "discarded") is a very different situation from one that never
  // ran at all (status "no_key"), even though both land on a structural engine_used.
  const noticeByStatus = {
    no_key: (
      <>
        Formatting was cleaned up, but no AI rewrite ran — wording and keyword coverage are
        unchanged from your original. Add a <code>GEMINI_API_KEY</code> or <code>GROQ_API_KEY</code> to
        enable rewriting.
      </>
    ),
    llm_failed: (
      <>
        Formatting was cleaned up, but the AI rewrite didn&rsquo;t come back usable this time.
        Wording and keyword coverage are unchanged from your original — try optimizing again.
      </>
    ),
    discarded: (
      <>
        An AI rewrite was generated, but it didn&rsquo;t score higher than your original resume, so
        we kept the stronger version instead. Nothing was lost — try again for another attempt.
      </>
    ),
  };
  const notice = noticeByStatus[audit.rewrite_status];

  return (
    <section className="audit">
      {notice && <p className="notice">{notice}</p>}

      <dl className="audit-list">
        <Row term="Breakdown">
          <ul className="component-scores">
            {components.map(([name, score]) => (
              <li key={name}>
                <span>{name}</span>
                <b>{score}%</b>
              </li>
            ))}
          </ul>
        </Row>

        <Row term="Coverage">
          {audit.matched_count} of {audit.matched_count + audit.missing_count} job-description terms
          matched
          {audit.missing_count > 0 && `, ${audit.missing_count} still missing`}
        </Row>

        {injected.length > 0 && (
          <Row term="Newly covered">
            <ul className="chips">
              {injected.map((keyword) => (
                <li className="chip" key={keyword}>
                  {keyword}
                </li>
              ))}
            </ul>
          </Row>
        )}

        {alerts.length > 0 && (
          <Row term="Formatting">
            <ul className="alerts">
              {alerts.map((alert) => (
                <li key={alert}>{alert}</li>
              ))}
            </ul>
          </Row>
        )}

        {writingTips.length > 0 && (
          <Row term="Writing">
            <ul className="alerts">
              {writingTips.map((tip) => (
                <li key={tip}>{tip}</li>
              ))}
            </ul>
          </Row>
        )}
      </dl>
    </section>
  );
}
