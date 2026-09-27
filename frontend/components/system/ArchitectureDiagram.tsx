'use client';

import { useEffect, useState } from 'react';
import { track } from '@/lib/analytics';
import { useInView, usePrefersReducedMotion } from '@/lib/site/useInView';

type Entry = 'sdk' | 'serve' | 'hook';
type Outcome = 'allow' | 'refuse';

type Node = { id: string; x: number; y: number; label: string; sub: string; w?: number };

/**
 * The substrate as one route. Whichever surface a call enters by, it
 * crosses the same boundary, is decided by the same gate, and lands in the
 * same chain. Allowed or refused, the relay records it: the only branch in
 * the whole diagram is whether the handler runs.
 */
const NODES: Node[] = [
  { id: 'agent', x: 360, y: 40, label: 'AGENT', sub: 'any agent loop' },
  { id: 'sdk', x: 150, y: 140, label: 'SDK', sub: 'mesh.execute()' },
  { id: 'serve', x: 360, y: 140, label: 'SERVE', sub: 'OpenAI-compatible' },
  { id: 'hook', x: 570, y: 140, label: 'HOOK', sub: 'policy check --stdin' },
  { id: 'boundary', x: 360, y: 240, label: 'BOUNDARY', sub: 'LifecycleBoundary' },
  { id: 'gate', x: 330, y: 340, label: 'GATE', sub: 'returns a Verdict' },
  { id: 'contract', x: 600, y: 296, label: 'CONTRACT', sub: 'causalmesh.yaml', w: 140 },
  { id: 'claims', x: 600, y: 340, label: 'CLAIMS', sub: 'exclusive leases', w: 140 },
  { id: 'ledger', x: 600, y: 384, label: 'LEDGER', sub: 'Decimal, shared', w: 140 },
  { id: 'handler', x: 200, y: 450, label: 'HANDLER', sub: 'runs only if allowed' },
  { id: 'refusal', x: 460, y: 450, label: 'REFUSAL', sub: 'kept with its reason' },
  { id: 'relay', x: 330, y: 540, label: 'RELAY', sub: 'ingests either way' },
  { id: 'chain', x: 200, y: 630, label: 'SIGNED CHAIN', sub: 'Ed25519, hash-linked' },
  { id: 'verify', x: 460, y: 630, label: 'VERIFY', sub: 'offline, anywhere' },
];

const EDGES: Record<string, string> = {
  'agent-sdk': 'M360 62 V100 H150 V118',
  'agent-serve': 'M360 62 V118',
  'agent-hook': 'M360 62 V100 H570 V118',
  'sdk-boundary': 'M150 162 V200 H360 V218',
  'serve-boundary': 'M360 162 V218',
  'hook-boundary': 'M570 162 V200 H360 V218',
  'boundary-gate': 'M360 262 V290 H330 V318',
  'gate-policy': 'M415 340 H530 M490 340 V296 H530 M490 340 V384 H530',
  'gate-handler': 'M330 362 V400 H200 V428',
  'gate-refusal': 'M330 362 V400 H460 V428',
  'handler-relay': 'M200 472 V505 H330 V518',
  'refusal-relay': 'M460 472 V505 H330 V518',
  'relay-chain': 'M330 562 V595 H200 V608',
  'chain-verify': 'M285 630 H375',
};

function activePath(entry: Entry, outcome: Outcome) {
  const branch = outcome === 'allow' ? 'handler' : 'refusal';
  const nodes = new Set(['agent', entry, 'boundary', 'gate', 'contract', 'claims', 'ledger', branch, 'relay', 'chain', 'verify']);
  const edges = new Set([
    `agent-${entry}`,
    `${entry}-boundary`,
    'boundary-gate',
    'gate-policy',
    `gate-${branch}`,
    `${branch}-relay`,
    'relay-chain',
    'chain-verify',
  ]);
  return { nodes, edges };
}

const SEQUENCE: Array<[Entry, Outcome]> = [
  ['sdk', 'allow'],
  ['serve', 'refuse'],
  ['hook', 'allow'],
  ['sdk', 'refuse'],
  ['serve', 'allow'],
  ['hook', 'refuse'],
];

const STAGES = [
  ['AGENT', 'any agent loop'],
  ['ENTRY', 'SDK  /  serve  /  hook'],
  ['BOUNDARY', 'the one control point'],
  ['GATE', 'contract, claims, ledger'],
  ['VERDICT', 'handler runs, or refusal kept'],
  ['RELAY', 'ingests either way'],
  ['SIGNED CHAIN', 'verifies offline'],
];

export function ArchitectureDiagram() {
  const { ref, inView } = useInView<HTMLDivElement>({ once: false, rootMargin: '0px' });
  const reduced = usePrefersReducedMotion();
  const [step, setStep] = useState(0);
  const [pinned, setPinned] = useState(false);
  const [entry, outcome] = SEQUENCE[step % SEQUENCE.length];

  useEffect(() => {
    if (!inView || reduced || pinned) return;
    const id = window.setInterval(() => setStep((s) => s + 1), 2600);
    return () => window.clearInterval(id);
  }, [inView, reduced, pinned]);

  const choose = (next: Entry | Outcome) => {
    setPinned(true);
    const e = next === 'allow' || next === 'refuse' ? entry : next;
    const o = next === 'allow' || next === 'refuse' ? next : outcome;
    const index = SEQUENCE.findIndex(([a, b]) => a === e && b === o);
    setStep(index);
    track('architecture_route', { entry: e, outcome: o });
  };

  const { nodes, edges } = activePath(entry, outcome);
  const refused = outcome === 'refuse';

  return (
    <div ref={ref}>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3" role="group" aria-label="Route">
        <Toggle label="Entry" options={['sdk', 'serve', 'hook']} value={entry} onChange={choose} />
        <Toggle label="Verdict" options={['allow', 'refuse']} value={outcome} onChange={choose} />
      </div>

      <p className="sr-only" aria-live="polite">
        {`Call enters through ${entry}, the gate ${refused ? 'refuses it and the refusal is recorded' : 'allows it and the handler runs'}, and the relay writes it to the signed chain.`}
      </p>

      {/* Desktop and tablet: the full routed tree. */}
      <svg
        viewBox="40 10 690 650"
        className="mt-8 hidden w-full md:block"
        role="img"
        aria-label="Architecture: agent, three entry surfaces, boundary, gate with contract, claims and ledger, handler or refusal, relay, signed chain, offline verification."
      >
        {Object.entries(EDGES).map(([id, d]) => {
          const on = edges.has(id);
          const deny = on && refused && (id === 'gate-refusal' || id === 'refusal-relay');
          return (
            <path
              key={id}
              d={d}
              fill="none"
              strokeWidth={1}
              className={on ? 'route' : ''}
              stroke={deny ? 'var(--color-deny)' : on ? 'var(--color-fg-2)' : 'rgb(255 255 255 / 0.12)'}
              style={{ transition: 'stroke 0.5s var(--ease-out-site)' }}
            />
          );
        })}
        {NODES.map((n) => {
          const w = n.w ?? 170;
          const h = n.w ? 36 : 44;
          const on = nodes.has(n.id);
          const deny = on && n.id === 'refusal';
          return (
            <g key={n.id} transform={`translate(${n.x - w / 2} ${n.y - h / 2})`}>
              <rect
                width={w}
                height={h}
                rx={3}
                fill="var(--color-stage-panel)"
                stroke={deny ? 'var(--color-deny)' : on ? 'rgb(255 255 255 / 0.55)' : 'rgb(255 255 255 / 0.1)'}
                style={{ transition: 'stroke 0.5s var(--ease-out-site)' }}
              />
              <text
                x={12}
                y={n.w ? 15 : 18}
                fontFamily="var(--font-code)"
                fontSize={10.5}
                letterSpacing="0.1em"
                fill={deny ? 'var(--color-deny)' : on ? 'var(--color-fg)' : 'var(--color-dim)'}
                style={{ transition: 'fill 0.5s var(--ease-out-site)' }}
              >
                {n.label}
              </text>
              <text
                x={12}
                y={n.w ? 29 : 34}
                fontFamily="var(--font-site)"
                fontSize={11.5}
                fill={on ? 'var(--color-muted)' : 'var(--color-faint)'}
                style={{ transition: 'fill 0.5s var(--ease-out-site)' }}
              >
                {n.sub}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Phone: the same route as a stack, which stays legible at 360px. */}
      <ol className="mt-8 md:hidden">
        {STAGES.map(([label, sub], i) => {
          const isVerdict = label === 'VERDICT';
          return (
            <li key={label} className="relative flex gap-4 pb-5 last:pb-0">
              <span
                aria-hidden="true"
                className={`absolute left-[3px] top-3 h-full w-px ${i === STAGES.length - 1 ? 'hidden' : ''} bg-line-strong`}
              />
              <span
                aria-hidden="true"
                className={`relative mt-[7px] h-[7px] w-[7px] shrink-0 rounded-full ${isVerdict && refused ? 'bg-deny' : 'bg-fg'}`}
              />
              <div>
                <div className={`label ${isVerdict && refused ? '!text-deny' : '!text-fg-2'}`}>
                  {isVerdict ? (refused ? 'REFUSAL' : 'HANDLER') : label === 'ENTRY' ? entry.toUpperCase() : label}
                </div>
                <div className="mt-1 text-[13.5px] text-muted">{sub}</div>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Toggle<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: T[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="label">{label}</span>
      <div className="flex rounded-full border border-line p-[3px]">
        {options.map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={value === option}
            onClick={() => onChange(option)}
            className={`min-h-[32px] rounded-full px-3.5 font-code text-[11.5px] uppercase tracking-[0.08em] transition-colors duration-300 ${
              value === option
                ? option === 'refuse'
                  ? 'bg-deny-wash text-deny'
                  : 'bg-white/10 text-fg'
                : 'text-dim hover:text-fg-2'
            }`}
          >
            {option}
          </button>
        ))}
      </div>
    </div>
  );
}
