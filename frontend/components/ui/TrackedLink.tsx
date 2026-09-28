'use client';

import type { AnchorHTMLAttributes, ReactNode } from 'react';
import { track, type TrackEvent } from '@/lib/analytics';

/**
 * An anchor that reports intent when followed. The whole reason it is a
 * client component; everything else about it is a plain link.
 */
export function TrackedLink({
  event,
  props,
  children,
  onClick,
  ...rest
}: AnchorHTMLAttributes<HTMLAnchorElement> & {
  event: TrackEvent;
  props?: Record<string, string>;
  children: ReactNode;
}) {
  return (
    <a
      {...rest}
      onClick={(e) => {
        track(event, { href: rest.href, ...props });
        onClick?.(e);
      }}
    >
      {children}
    </a>
  );
}
