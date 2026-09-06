/**
 * Renderer for the restricted markdown subset the engine emits.
 *
 * The engine produces a fixed shape: one '# ' title, a contact line, '## ' sections,
 * '### ' role headings, '- ' bullets and plain paragraphs. Nothing else is supported,
 * which is the point — the output is parsed into React elements rather than assembled
 * into an HTML string, so resume text can never be interpreted as markup.
 */

import React from 'react';

/** Split a line on **bold** spans, returning React nodes. */
function renderInline(text, keyPrefix) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts
    .filter(Boolean)
    .map((part, index) =>
      part.startsWith('**') && part.endsWith('**') ? (
        <strong key={`${keyPrefix}-b${index}`}>{part.slice(2, -2)}</strong>
      ) : (
        <React.Fragment key={`${keyPrefix}-t${index}`}>{part}</React.Fragment>
      ),
    );
}

export function renderResumeMarkdown(markdown) {
  if (!markdown) return null;

  const lines = markdown.split('\n');
  const blocks = [];
  let bullets = [];
  let titleSeen = false;

  const flushBullets = () => {
    if (!bullets.length) return;
    blocks.push(
      <ul className="sheet-list" key={`ul-${blocks.length}`}>
        {bullets.map((item, index) => (
          <li key={`li-${blocks.length}-${index}`}>{renderInline(item, `li-${blocks.length}-${index}`)}</li>
        ))}
      </ul>,
    );
    bullets = [];
  };

  lines.forEach((raw, index) => {
    const line = raw.trim();
    if (!line) return;

    if (line.startsWith('# ') && !titleSeen) {
      flushBullets();
      titleSeen = true;
      blocks.push(
        <h1 className="sheet-name" key={`h1-${index}`}>
          {line.slice(2).trim()}
        </h1>,
      );
      return;
    }

    // The contact line is the unmarked line directly beneath the name.
    if (titleSeen && index <= 3 && !line.startsWith('#') && !line.startsWith('- ') && (line.includes('|') || line.includes('@'))) {
      flushBullets();
      blocks.push(
        <p className="sheet-contact" key={`contact-${index}`}>
          {line}
        </p>,
      );
      return;
    }

    if (line.startsWith('## ')) {
      flushBullets();
      blocks.push(
        <h2 className="sheet-section" key={`h2-${index}`}>
          {line.slice(3).trim()}
        </h2>,
      );
      return;
    }

    if (line.startsWith('### ')) {
      flushBullets();
      blocks.push(
        <h3 className="sheet-role" key={`h3-${index}`}>
          {renderInline(line.slice(4).trim(), `h3-${index}`)}
        </h3>,
      );
      return;
    }

    if (line.startsWith('- ') || line.startsWith('* ')) {
      bullets.push(line.slice(2).trim());
      return;
    }

    flushBullets();
    blocks.push(
      <p className="sheet-text" key={`p-${index}`}>
        {renderInline(line, `p-${index}`)}
      </p>,
    );
  });

  flushBullets();
  return blocks;
}
