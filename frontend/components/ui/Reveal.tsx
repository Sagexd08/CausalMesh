'use client';

import type { CSSProperties, ElementType, ReactNode } from 'react';
import { useInView } from '@/lib/site/useInView';

/** Opacity and a short rise on first entry. Styles live in app/site.css. */
export function Reveal({
  as: Tag = 'div',
  index = 0,
  className = '',
  children,
}: {
  as?: ElementType;
  index?: number;
  className?: string;
  children: ReactNode;
}) {
  const { ref, inView } = useInView<HTMLElement>();
  return (
    <Tag
      ref={ref}
      data-in={inView ? '' : undefined}
      className={`reveal ${className}`}
      style={{ '--i': index } as CSSProperties}
    >
      {children}
    </Tag>
  );
}
