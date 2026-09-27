'use client';

import { useState, type ReactNode } from 'react';
import { track } from '@/lib/analytics';

const KEYWORDS = new Set(
  'from import as def return if else elif for in not and or with async await True False None'.split(' '),
);

/**
 * A deliberately small highlighter: comments, strings, keywords, and the
 * shell prompt. Enough to make code read as code, without shipping a
 * grammar engine to colour eight lines.
 */
function highlight(line: string): ReactNode[] {
  if (/^\s*#/.test(line)) return [<span key="c" className="text-dim">{line}</span>];
  if (line.startsWith('$ ')) {
    return [
      <span key="p" className="text-dim select-none">$ </span>,
      <span key="r" className="text-fg">{line.slice(2)}</span>,
    ];
  }
  // A trailing comment: the first # that sits outside a string.
  const hash = line.replace(/"[^"]*"|'[^']*'/g, (m) => ' '.repeat(m.length)).indexOf('#');
  if (hash > 0) {
    return [...highlight(line.slice(0, hash)), <span key="tc" className="text-dim">{line.slice(hash)}</span>];
  }
  const parts = line.split(/("[^"]*"|'[^']*')/g);
  return parts.map((part, i) => {
    if (/^["']/.test(part)) return <span key={i} className="text-strip">{part}</span>;
    return part.split(/(\b\w+\b)/g).map((word, j) =>
      KEYWORDS.has(word) ? (
        <span key={`${i}-${j}`} className="text-muted">{word}</span>
      ) : (
        <span key={`${i}-${j}`} className="text-fg-2">{word}</span>
      ),
    );
  });
}

export function CodeBlock({
  title,
  code,
  copyId,
  className = '',
}: {
  title: string;
  code: string;
  copyId: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    const text = code
      .split('\n')
      .map((l) => (l.startsWith('$ ') ? l.slice(2) : l))
      .join('\n');
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      track('code_copy', { block: copyId });
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className={`panel overflow-hidden ${className}`}>
      <div className="panel-head">
        <span>{title}</span>
        <button
          type="button"
          onClick={copy}
          className="rounded px-1.5 py-0.5 text-dim transition-colors hover:text-fg"
          aria-label={`Copy ${title}`}
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-x-auto p-5 font-code text-[13px] leading-[1.75]">
        <code>
          {code.split('\n').map((line, i) => (
            <span key={i} className="block min-h-[1.75em]">
              {highlight(line)}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
