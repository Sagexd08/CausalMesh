import type { ReactNode } from 'react';
import { Reveal } from './Reveal';

export function Container({ className = '', children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`mx-auto w-full max-w-[1320px] px-6 sm:px-10 lg:px-16 ${className}`}>
      {children}
    </div>
  );
}

export function Section({
  id,
  className = '',
  children,
}: {
  id?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section id={id} className={`scroll-mt-8 border-t border-line py-24 md:py-32 ${className}`}>
      <Container>{children}</Container>
    </section>
  );
}

/** Small mono index label: "01 / GATE". */
export function Label({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`label ${className}`}>{children}</div>;
}

/**
 * The heading block every product section opens with: an index, a short
 * claim, and one paragraph. The claim is the only large type below the hero.
 */
export function SectionHead({
  index,
  title,
  children,
  className = '',
}: {
  index: string;
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <Reveal>
        <Label>{index}</Label>
      </Reveal>
      <Reveal index={1}>
        <h2 className="mt-5 max-w-[20ch] text-[clamp(2rem,1.4rem+2.2vw,3.25rem)] font-light leading-[1.05] tracking-[-0.04em] text-fg [text-wrap:balance]">
          {title}
        </h2>
      </Reveal>
      {children && (
        <Reveal index={2}>
          <p className="mt-6 max-w-[52ch] text-[16px] leading-[1.65] text-muted">{children}</p>
        </Reveal>
      )}
    </div>
  );
}

export function StatusDot({ tone = 'ok' }: { tone?: 'ok' | 'deny' | 'idle' }) {
  const color = tone === 'deny' ? 'bg-deny' : tone === 'idle' ? 'bg-faint' : 'bg-fg';
  return <span aria-hidden="true" className={`inline-block h-[6px] w-[6px] rounded-full ${color}`} />;
}
