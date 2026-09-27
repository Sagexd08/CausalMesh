import type { ReactNode } from 'react';
import { StatusDot } from '@/components/ui/Section';

/** A fragment of the machine: a hairline frame with a mono title bar. */
export function Panel({
  title,
  status,
  tone = 'ok',
  className = '',
  children,
}: {
  title: ReactNode;
  status?: ReactNode;
  tone?: 'ok' | 'deny' | 'idle';
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`panel overflow-hidden ${className}`}>
      <div className="panel-head">
        <span className="truncate">{title}</span>
        {status && (
          <span className="flex shrink-0 items-center gap-2 text-fg-2">
            <StatusDot tone={tone} />
            {status}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

/** One measurement: a label, a value, and the unit it is measured in. */
export function Metric({
  label,
  value,
  unit,
  note,
  tone,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  note?: ReactNode;
  tone?: 'deny';
}) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className="mt-2 flex items-baseline gap-1.5">
        <span
          className={`tabular text-[26px] font-light tracking-[-0.03em] ${
            tone === 'deny' ? 'text-deny' : 'text-fg'
          }`}
        >
          {value}
        </span>
        {unit && <span className="font-code text-[11.5px] text-dim">{unit}</span>}
      </div>
      {note && <div className="mt-1 text-[12.5px] leading-snug text-dim">{note}</div>}
    </div>
  );
}

export function MetricGrid({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line bg-line ${className}`}
    >
      {children}
    </div>
  );
}

export function MetricCell({ children }: { children: ReactNode }) {
  return <div className="bg-stage-panel p-5">{children}</div>;
}
