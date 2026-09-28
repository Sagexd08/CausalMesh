'use client';

import { useEffect, useState } from 'react';
import { TRACE, TRACE_RUN, TRACE_SUMMARY } from '@/lib/site/content';
import { useInView, usePrefersReducedMotion } from '@/lib/site/useInView';
import { Metric } from './Panel';

/**
 * The signed chain of one real run, line by line, followed by what
 * `verify` says about it. Timestamps are relative to the run's
 * deterministic clock: the chain carries no wall-clock time, because
 * nothing non-reproducible may be signed.
 */
const TAIL = [
  { text: `chain verified  4/4 events  head ${TRACE_SUMMARY.headHash.slice(0, 16)}...`, tone: 'ok' },
  { text: `outcome  ${TRACE_SUMMARY.outcome}`, tone: 'deny' },
] as const;

export function ExecutionTrace() {
  const { ref, inView } = useInView<HTMLDivElement>({ once: false, rootMargin: '0px' });
  const reduced = usePrefersReducedMotion();
  const total = TRACE.length + TAIL.length;
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (!inView) return;
    if (reduced) {
      setShown(total);
      return;
    }
    const id = window.setTimeout(
      () => setShown((n) => (n >= total + 3 ? 0 : n + 1)),
      shown === 0 ? 500 : shown >= total ? 1400 : 900,
    );
    return () => window.clearTimeout(id);
  }, [inView, reduced, shown, total]);

  const live = shown > 0 && shown < total;
  const eventsShown = Math.min(shown, TRACE.length);
  const denials = TRACE.slice(0, eventsShown).filter((e) => e.outcome === 'denied').length;

  return (
    <div ref={ref} className="grid grid-cols-1 gap-px overflow-hidden rounded-md border border-line bg-line lg:grid-cols-[1fr_340px]">
      <div className="min-w-0 bg-stage-panel">
        <div className="panel-head">
          <span>Execution trace</span>
          <span className="flex items-center gap-2 text-fg-2">
            <span
              aria-hidden="true"
              className={`inline-block h-[6px] w-[6px] rounded-full ${live ? 'animate-pulse bg-fg' : 'bg-faint'}`}
            />
            {live ? 'replaying' : 'recorded'}
          </span>
        </div>
        <div className="overflow-x-auto">
          <ol className="min-w-[620px] p-5 font-code text-[12px] leading-[2]">
            {TRACE.map((e, i) => (
              <li
                key={e.seq}
                className="grid grid-cols-[62px_28px_72px_68px_1fr_92px] gap-2 transition-opacity duration-500"
                style={{ opacity: i < shown ? 1 : 0.12 }}
              >
                <span className="text-dim">{e.t}s</span>
                <span className="text-faint">{e.seq}</span>
                <span className={e.outcome === 'denied' ? 'text-deny' : 'text-fg'}>{e.type}</span>
                <span className="text-fg-2">{e.agent}</span>
                <span className={`truncate ${e.outcome === 'denied' ? 'text-deny' : 'text-muted'}`}>
                  {e.path} &middot; {e.detail}
                </span>
                <span className="text-right text-faint">{e.hash}</span>
              </li>
            ))}
            {TAIL.map((line, i) => (
              <li
                key={line.text}
                className={`transition-opacity duration-500 ${i === 0 ? 'mt-3 border-t border-line pt-3' : ''} ${
                  line.tone === 'deny' ? 'text-deny' : 'text-fg-2'
                }`}
                style={{ opacity: TRACE.length + i < shown ? 1 : 0.12 }}
              >
                {line.text}
              </li>
            ))}
          </ol>
        </div>
        <div className="border-t border-line px-5 py-3 font-code text-[11px] text-faint">
          <span className="text-dim">run</span> {TRACE_RUN}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-px bg-line">
        <div className="bg-stage-panel p-5"><Metric label="Events" value={eventsShown} unit={`/ ${TRACE_SUMMARY.events}`} /></div>
        <div className="bg-stage-panel p-5"><Metric label="Denials" value={denials} unit="recorded" tone={denials ? 'deny' : undefined} /></div>
        <div className="bg-stage-panel p-5"><Metric label="Append p50" value={TRACE_SUMMARY.appendP50us} unit="µs" note={`p99 ${TRACE_SUMMARY.appendP99us} µs`} /></div>
        <div className="bg-stage-panel p-5"><Metric label="Hook p50" value={TRACE_SUMMARY.hookP50us} unit="µs" note={`p99 ${TRACE_SUMMARY.hookP99us} µs`} /></div>
        <div className="bg-stage-panel p-5"><Metric label="Coordination" value={TRACE_SUMMARY.coordinationBytes} unit="B / run" /></div>
        <div className="bg-stage-panel p-5"><Metric label="Key ring" value={<span className="font-code text-[13px] tracking-normal">{TRACE_SUMMARY.keyRing}</span>} note="Ed25519" /></div>
      </div>
    </div>
  );
}
