import { useCallback, useId, useRef, useState } from 'react';
import { extractFile } from '../api';

const ACCEPTED = '.pdf,.docx,.doc,.txt,.md';

/**
 * One of the two source documents: a drop target, a file picker and an editable
 * textarea over the same value. Uploading extracts text server-side and drops it
 * into the textarea, so the user can always review and edit what was parsed.
 */
export default function DocumentInput({ ordinal, label, hint, placeholder, value, onChange, onNotify }) {
  const inputRef = useRef(null);
  const fieldId = useId();
  const [dragging, setDragging] = useState(false);
  const [status, setStatus] = useState(null); // { tone: 'ok' | 'error', message }

  const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0;

  const ingest = useCallback(
    async (file) => {
      if (!file) return;
      // PDFs with no real text layer fall back to OCR server-side, which is genuinely
      // slower (rendering + reading each page as an image) - set that expectation up
      // front rather than letting a normal-looking spinner sit for up to a minute.
      const isPdf = /\.pdf$/i.test(file.name);
      setStatus({
        tone: 'busy',
        message: isPdf
          ? `Extracting text from ${file.name}… this can take up to a minute for a scanned document.`
          : `Extracting text from ${file.name}…`,
      });
      try {
        const data = await extractFile(file);
        onChange(data.text);
        if (data.word_count === 0) {
          // Extraction technically succeeded (no error), but found nothing to read - most
          // often a PDF whose fonts lack the encoding info needed to recover text (OCR
          // already ran and still found nothing). This must not look like success.
          setStatus({
            tone: 'error',
            message: isPdf
              ? `Could not read any text from ${file.name}, even after trying OCR (it may be a very ` +
                'low-resolution scan, blank, or corrupted). Try a clearer scan, a DOCX file, or paste ' +
                'the text in below instead.'
              : `Could not read any text from ${file.name}. Try a different file, or paste the text in below.`,
          });
        } else {
          setStatus({ tone: 'ok', message: `Extracted ${data.word_count} words from ${file.name}` });
          onNotify(`Loaded ${label.toLowerCase()} from ${file.name}`);
        }
      } catch (error) {
        setStatus({ tone: 'error', message: error.message });
      }
    },
    [label, onChange, onNotify],
  );

  const onDrop = (event) => {
    event.preventDefault();
    setDragging(false);
    ingest(event.dataTransfer.files?.[0]);
  };

  return (
    <section className="panel">
      <header className="panel-head">
        <div className="panel-title">
          <span className="ordinal">{ordinal}</span>
          <h2>{label}</h2>
        </div>
        <span className="counter">{wordCount.toLocaleString()} words</span>
      </header>

      <div
        className={`dropzone${dragging ? ' is-dragging' : ''}`}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        role="button"
        tabIndex={0}
        aria-label={`Upload ${label}`}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          hidden
          onChange={(event) => {
            ingest(event.target.files?.[0]);
            event.target.value = ''; // allow re-selecting the same file
          }}
        />
        <p className="dropzone-lead">
          Drop a file here, or <span className="link-like">browse</span>
        </p>
        <p className="dropzone-hint">{hint}</p>
      </div>

      {status && <p className={`field-status is-${status.tone}`}>{status.message}</p>}

      <label className="sr-only" htmlFor={fieldId}>
        {label}
      </label>
      <textarea
        id={fieldId}
        className="editor"
        placeholder={placeholder}
        value={value}
        spellCheck="false"
        onChange={(event) => onChange(event.target.value)}
      />
    </section>
  );
}
