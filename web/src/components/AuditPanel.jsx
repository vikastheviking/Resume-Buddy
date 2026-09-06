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
  const structural = (audit.engine_used ?? '').startsWith('structural');

  const components = [
    ['Keywords', audit.keyword_score],
    ['Semantic', audit.semantic_score],
    ['Impact', audit.impact_score],
    ['Format', audit.format_score],
  ];

  return (
    <section className="audit">
      {structural && (
        <p className="notice">
          Formatting was cleaned up, but no AI rewrite ran — wording and keyword coverage are
          unchanged from your original. Add a <code>GROQ_API_KEY</code> to enable rewriting.
        </p>
      )}

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
      </dl>
    </section>
  );
}
