'use client';

import { useEffect, useState } from 'react';
import { track } from '@/lib/analytics';
import { VERDICTS, type VerdictExample } from '@/lib/site/content';
import { useInView, usePrefersReducedMotion } from '@/lib/site/useInView';
import { StatusDot } from '@/components/ui/Section';

function command(v: VerdictExample) {
  const amount = v.amount ? ` --amount ${v.amount}` : '';
  return `causalmesh policy check --agent ${v.agent} --kind ${v.kind} --name ${v.name}${amount}`;
}

/**
 * Four checks against this repository's own contract, replayed. Each one is
 * the verdict the real CLI returned; the console only adds the typing.
 */
export function VerdictConsole() {
  const { ref, inView } = useInView<HTMLDivElement>({ once: false, rootMargin: '0px' });
  const reduced = usePrefersReducedMotion();
  const [index, setIndex] = useState(0);
  const [typed, setTyped] = useState(0);
  const [pinned, setPinned] = useState(false);

  const verdict = VERDICTS[index];
  const cmd = command(verdict);
  const done = reduced || typed >= cmd.length;

  // Type the command, then hold the verdict, then advance.
  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setTyped(cmd.length);
      return;
    }
    if (typed < cmd.length) {
      const id = window.setTimeout(() => setTyped((t) => Math.min(cmd.length, t + 3)), 16);
      return () => window.clearTimeout(id);
    }
    if (pinned) return;
    const id = window.setTimeout(() => {
      setIndex((i) => (i + 1) % VERDICTS.length);
      setTyped(0);
    }, 3600);
    return () => window.clearTimeout(id);
  }, [inView, reduced, typed, cmd.length, pinned]);

  const select = (i: number) => {
    setPinned(true);
    setIndex(i);
    setTyped(reduced ? Number.MAX_SAFE_INTEGER : 0);
    track('gate_example', { agent: VERDICTS[i].agent, allowed: VERDICTS[i].allowed });
  };

  return (
    <div ref={ref} className="grid grid-cols-1 gap-px overflow-hidden rounded-md border border-line bg-line lg:grid-cols-[260px_1fr]">
      <div className="bg-stage-panel">
        <div className="panel-head">Requests</div>
        <ul>
          {VERDICTS.map((v, i) => (
            <li key={i}>
              <button
                type="button"
                onClick={() => select(i)}
                aria-pressed={i === index}
                className={`flex w-full items-center gap-3 border-b border-line px-4 py-3.5 text-left transition-colors duration-300 last:border-0 ${
                  i === index ? 'bg-white/[0.04]' : 'hover:bg-white/[0.02]'
                }`}
              >
                <StatusDot tone={v.allowed ? 'ok' : 'deny'} />
                <span className="min-w-0">
                  <span className="block font-code text-[12px] text-fg-2">{v.agent}</span>
                  <span className="block truncate font-code text-[11.5px] text-dim">
                    {v.kind}:{v.name}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="min-w-0 bg-stage-panel">
        <div className="panel-head">
          <span>Gate</span>
          <span className="text-dim">causalmesh.yaml &middot; arm C3</span>
        </div>
        <div className="min-h-[300px] p-5 font-code text-[12.5px] leading-[1.8]" aria-live="polite">
          <div className="break-all text-fg-2">
            <span className="select-none text-dim">$ </span>
            {cmd.slice(0, typed)}
            {!done && <span className="caret" />}
          </div>

          <div
            className="mt-5 transition-opacity duration-500"
            style={{ opacity: done ? 1 : 0 }}
          >
            <div className="flex items-center gap-3">
              <span
                className={`rounded-sm px-2 py-0.5 text-[11px] tracking-[0.1em] ${
                  verdict.allowed ? 'bg-white/10 text-fg' : 'bg-deny-wash text-deny'
                }`}
              >
                {verdict.allowed ? 'ALLOW' : 'REFUSE'}
              </span>
              <span className="truncate text-muted">
                {verdict.kind}:{verdict.name}
              </span>
            </div>

            <dl className="mt-5 grid grid-cols-[88px_1fr] gap-y-1.5">
              <dt className="text-dim">rule</dt>
              <dd className="text-fg-2">{verdict.rule}</dd>
              <dt className="text-dim">holder</dt>
              <dd className="text-fg-2">{verdict.holder ?? 'null'}</dd>
              <dt className="text-dim">reason</dt>
              <dd className="break-words text-fg-2">{verdict.reason}</dd>
              <dt className="text-dim">exit</dt>
              <dd className={verdict.allowed ? 'text-fg-2' : 'text-deny'}>
                {verdict.allowed ? '0' : '1'}
              </dd>
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}
