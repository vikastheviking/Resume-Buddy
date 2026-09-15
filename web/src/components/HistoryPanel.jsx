import { useEffect, useState } from 'react';
import { supabase } from '../supabaseClient';

/**
 * Past optimizations for the signed-in user.
 *
 * Reads and deletes go straight to Supabase with the user's own session - RLS on the
 * `resumes` table (auth.uid() = user_id) is what actually keeps one user's history from
 * another's, not anything this component does.
 */
export default function HistoryPanel({ open, onClose, onSelect, onNotify }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [deletingId, setDeletingId] = useState(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    supabase
      .from('resumes')
      .select('id, jd_text, actual_score, updated_score, optimized_resume, parsed_data, created_at')
      .order('created_at', { ascending: false })
      .limit(20)
      .then(({ data, error: queryError }) => {
        if (queryError) {
          setError(queryError.message);
        } else {
          setRows(data);
        }
      });
  }, [open]);

  if (!open) return null;

  const deleteEntry = async (id) => {
    setDeletingId(id);
    try {
      const { error: deleteError } = await supabase.from('resumes').delete().eq('id', id);
      if (deleteError) throw deleteError;
      setRows((current) => current.filter((row) => row.id !== id));
      onNotify?.('Removed from history.');
    } catch (err) {
      onNotify?.(err.message);
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div
      className="overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="history-heading">
        <header className="dialog-head">
          <div>
            <p className="label">Resume-Buddy</p>
            <h2 id="history-heading" className="display-heading dialog-heading">
              Your optimization history
            </h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </header>

        {error && <p className="alert is-error">{error}</p>}

        {rows === null && !error && <p className="prose-note">Loading…</p>}

        {rows !== null && rows.length === 0 && (
          <p className="prose-note">
            No saved optimizations yet — run one and it will show up here automatically.
          </p>
        )}

        {rows !== null && rows.length > 0 && (
          <ul className="skill-gap-list">
            {rows.map((row) => {
              const jdSnippet = (row.jd_text || '').trim().split('\n')[0].slice(0, 80) || 'Untitled job description';
              const date = new Date(row.created_at).toLocaleString();
              return (
                <li key={row.id} className="skill-gap-card">
                  <div className="skill-gap-card-head">
                    <h3>{jdSnippet}</h3>
                    <span className="chip">
                      {row.actual_score}% → {row.updated_score}%
                    </span>
                  </div>
                  <p className="prose-note">{date}</p>
                  <div className="toolbar">
                    <button type="button" className="button button--ghost" onClick={() => onSelect(row)}>
                      View
                    </button>
                    <button
                      type="button"
                      className="button button--ghost"
                      disabled={deletingId === row.id}
                      onClick={() => deleteEntry(row.id)}
                    >
                      {deletingId === row.id ? 'Removing…' : 'Delete'}
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
