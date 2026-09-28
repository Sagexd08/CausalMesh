'use client';

import { track } from '@/lib/analytics';
import { FAQ } from '@/lib/site/content';

/** Renders `code` spans in an answer; everything else stays plain text. */
function withCode(text: string) {
  return text.split(/(`[^`]+`)/g).map((part, i) =>
    part.startsWith('`') ? (
      <code key={i} className="font-code text-[13.5px] text-fg-2">
        {part.slice(1, -1)}
      </code>
    ) : (
      part
    ),
  );
}

/** Native disclosure: keyboard, find-in-page and no-JS all work for free. */
export function FaqList() {
  return (
    <div className="border-t border-line">
      {FAQ.map((item) => (
        <details
          key={item.q}
          className="group border-b border-line"
          onToggle={(e) => {
            if ((e.currentTarget as HTMLDetailsElement).open) track('faq_open', { question: item.q });
          }}
        >
          <summary className="flex min-h-[64px] cursor-pointer list-none items-center justify-between gap-6 py-5 text-[17px] tracking-[-0.015em] text-fg [&::-webkit-details-marker]:hidden">
            {item.q}
            <span
              aria-hidden="true"
              className="relative h-3 w-3 shrink-0 before:absolute before:left-0 before:top-1/2 before:h-px before:w-3 before:bg-muted after:absolute after:left-1/2 after:top-0 after:h-3 after:w-px after:bg-muted after:transition-transform after:duration-300 group-open:after:scale-y-0"
            />
          </summary>
          <p className="max-w-[62ch] pb-6 text-[15px] leading-[1.7] text-muted">{withCode(item.a)}</p>
        </details>
      ))}
    </div>
  );
}
