'use client';

import { useEffect, useState } from 'react';
import { track } from '@/lib/analytics';
import { TRACE_RUN, TRACE_SUMMARY } from '@/lib/site/content';
import { useInView, usePrefersReducedMotion } from '@/lib/site/useInView';

/**
 * The claim history of one real C3 run, replayed step by step: three
 * leases issued, then agent_b's write to a file agent_a holds, refused.
 */
const STEPS = [
  { kind: 'claim', agent: 'agent_a', path: 'src/alpha.py', text: 'lease issued' },
  { kind: 'claim', agent: 'agent_a', path: 'src/config.py', text: 'lease issued' },
  { kind: 'claim', agent: 'agent_b', path: 'src/beta.py', text: 'lease issued' },
  { kind: 'deny', agent: 'agent_b', path: 'src/config.py', text: "write refused: held by 'agent_a'" },
] as const;

const FILES = ['src/alpha.py', 'src/config.py', 'src/beta.py'];
const AGENT_Y = { agent_a: 70, agent_b: 210 } as const;
const FILE_Y = [50, 140, 230];

export function ClaimReplay() {
  const { ref, inView } = useInView<HTMLDivElement>({ once: false, rootMargin: '0px' });
  const reduced = usePrefersReducedMotion();
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setStep(STEPS.length);
      return;
    }
    const id = window.setTimeout(
      () => setStep((s) => (s >= STEPS.length + 2 ? 0 : s + 1)),
      step === 0 ? 700 : 1500,
    );
    return () => window.clearTimeout(id);
  }, [inView, reduced, step]);

  const shown = STEPS.slice(0, Math.min(step, STEPS.length));
  const denial = shown.some((s) => s.kind === 'deny');

  return (
    <div ref={ref} className="panel overflow-hidden">
      <div className="panel-head">
        <span>Claim registry</span>
        <span className="flex items-center gap-2 text-fg-2">
          <span
            aria-hidden="true"
            className={`inline-block h-[6px] w-[6px] rounded-full ${denial ? 'bg-deny' : 'bg-fg'}`}
          />
          {denial ? '1 denial' : `${shown.length} active`}
        </span>
      </div>

      <svg viewBox="0 0 560 280" className="hidden w-full sm:block" role="img" aria-label="Two agents, three files. agent_a holds src/alpha.py and src/config.py, agent_b holds src/beta.py, and agent_b's write to src/config.py is refused.">
        {(['agent_a', 'agent_b'] as const).map((a) => (
          <g key={a} transform={`translate(24 ${AGENT_Y[a] - 18})`}>
            <rect width="120" height="36" rx="3" fill="var(--color-stage)" stroke="rgb(255 255 255 / 0.35)" />
            <text x="14" y="23" fontFamily="var(--font-code)" fontSize="12" fill="var(--color-fg)">{a}</text>
          </g>
        ))}
        {FILES.map((f, i) => (
          <g key={f} transform={`translate(376 ${FILE_Y[i] - 16})`}>
            <rect width="160" height="32" rx="3" fill="var(--color-stage)" stroke="rgb(255 255 255 / 0.14)" />
            <text x="14" y="21" fontFamily="var(--font-code)" fontSize="12" fill="var(--color-muted)">{f}</text>
          </g>
        ))}
        {shown.map((s, i) => {
          const y1 = AGENT_Y[s.agent];
          const y2 = FILE_Y[FILES.indexOf(s.path)];
          const deny = s.kind === 'deny';
          return (
            <g key={i}>
              <path
                d={`M144 ${y1} C 260 ${y1}, 260 ${y2}, ${deny ? 360 : 376} ${y2}`}
                fill="none"
                stroke={deny ? 'var(--color-deny)' : 'rgb(255 255 255 / 0.55)'}
                strokeWidth="1"
                strokeDasharray={deny ? '3 5' : undefined}
                className={deny ? '' : 'route'}
              />
              {deny && (
                <g transform={`translate(360 ${y2})`}>
                  <line x1="-6" y1="-6" x2="6" y2="6" stroke="var(--color-deny)" />
                  <line x1="-6" y1="6" x2="6" y2="-6" stroke="var(--color-deny)" />
                </g>
              )}
            </g>
          );
        })}
      </svg>

      <ol className="px-5 sm:border-t sm:border-line py-4 font-code text-[12px] leading-[1.9]" aria-live="polite">
        {STEPS.map((s, i) => (
          <li
            key={i}
            className="grid grid-cols-[22px_70px_1fr] gap-2 transition-opacity duration-500"
            style={{ opacity: i < step ? 1 : 0.18 }}
          >
            <span className="text-faint">{i}</span>
            <span className="text-fg-2">{s.agent}</span>
            <span className={s.kind === 'deny' ? 'text-deny' : 'text-muted'}>
              {s.path} &middot; {s.text}
            </span>
          </li>
        ))}
      </ol>

      <button
        type="button"
        onClick={() => {
          setStep(0);
          track('demo_interaction', { demo: 'claim_replay' });
        }}
        className="flex w-full items-center justify-between border-t border-line px-5 py-3 font-code text-[11px] uppercase tracking-[0.1em] text-dim transition-colors hover:text-fg"
      >
        <span className="truncate normal-case tracking-normal">{TRACE_RUN}</span>
        <span className="shrink-0 pl-4">Replay</span>
      </button>
      <span className="sr-only">{TRACE_SUMMARY.denial}</span>
    </div>
  );
}
