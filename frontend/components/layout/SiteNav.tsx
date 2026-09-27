'use client';

import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { track } from '@/lib/analytics';
import { LINKS, NAV } from '@/lib/site/content';
import { BrandMark } from './BrandMark';

/**
 * The hero's navigation: brand left, links centred, one action right, laid
 * directly on the stage with no bar behind it.
 *
 * The full-screen menu is a sibling of the nav rather than a child. The
 * nav runs an entrance transform, and a transformed ancestor would become
 * the containing block for the menu's `position: fixed`, pinning a
 * "full-screen" overlay to the nav's own box.
 */
export function SiteNav({ base = '' }: { base?: string }) {
  // Section anchors resolve against the landing page when rendered elsewhere.
  const href = (to: string) => (to.startsWith('#') ? `${base}${to}` : to);
  const [open, setOpen] = useState(false);
  const burgerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) burgerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;

    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    menuRef.current?.querySelector<HTMLElement>('a')?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        close();
        return;
      }
      // Keep Tab inside the menu and the burger that closes it.
      if (e.key === 'Tab' && menuRef.current && burgerRef.current) {
        const items = [
          burgerRef.current,
          ...menuRef.current.querySelectorAll<HTMLElement>('a[href]'),
        ];
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    const desktop = window.matchMedia('(min-width: 1024px)');
    const onResize = () => desktop.matches && close(false);

    window.addEventListener('keydown', onKey);
    desktop.addEventListener('change', onResize);
    return () => {
      document.body.style.overflow = previous;
      window.removeEventListener('keydown', onKey);
      desktop.removeEventListener('change', onResize);
    };
  }, [open, close]);

  const toggle = () => {
    setOpen((value) => {
      if (!value) track('menu_open');
      return !value;
    });
  };

  return (
    <>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[70] focus:rounded-full focus:bg-pill focus:px-4 focus:py-2 focus:text-[14px] focus:text-pill-ink"
      >
        Skip to content
      </a>

      <nav aria-label="Primary" className="hero-nav" style={{ zIndex: 70 }}>
        <a href="/" aria-label="CausalMesh home" className="enter justify-self-start" style={{ '--i': 0 } as CSSProperties}>
          <BrandMark className="hero-brand" title="" />
        </a>

        <ul className="hero-links enter" style={{ '--i': 1 } as CSSProperties}>
          {NAV.map((item) => (
            <li key={item.label}>
              <a href={href(item.href)}>{item.label}</a>
            </li>
          ))}
        </ul>

        <div className="enter flex items-center justify-self-end gap-3" style={{ '--i': 2 } as CSSProperties}>
          <a
            href={LINKS.quickstart}
            onClick={() => track('hero_cta', { placement: 'nav' })}
            className="pill pill-sm hidden sm:inline-flex"
          >
            Get Started
          </a>
          <button
            ref={burgerRef}
            type="button"
            className="burger lg:hidden"
            aria-expanded={open}
            aria-controls="site-menu"
            aria-label={open ? 'Close menu' : 'Open menu'}
            onClick={toggle}
          >
            <i />
            <i />
          </button>
        </div>
      </nav>

      <div
        id="site-menu"
        ref={menuRef}
        className="menu lg:hidden"
        data-open={open}
        role="dialog"
        aria-modal="true"
        aria-label="Menu"
        aria-hidden={!open}
        inert={!open}
      >
        <div className="mt-[76px] label" data-stagger style={{ '--i': 0 } as CSSProperties}>
          Menu
        </div>
        <ul className="mt-6 flex flex-col">
          {NAV.map((item, i) => (
            <li key={item.label} data-stagger style={{ '--i': i + 1 } as CSSProperties}>
              <a
                href={href(item.href)}
                onClick={() => close(false)}
                className="flex min-h-[64px] items-center border-b border-line text-[34px] font-light tracking-[-0.035em] text-fg"
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
        <div
          className="mt-auto flex flex-wrap items-center gap-6 pt-10"
          data-stagger
          style={{ '--i': NAV.length + 1 } as CSSProperties}
        >
          <a
            href={LINKS.quickstart}
            className="pill"
            onClick={() => {
              track('menu_cta', { cta: 'get_started' });
              close(false);
            }}
          >
            Get Started
          </a>
          <a
            href={href(LINKS.architecture)}
            className="ghost"
            onClick={() => {
              track('menu_cta', { cta: 'view_architecture' });
              close(false);
            }}
          >
            View Architecture <span aria-hidden="true">&rarr;</span>
          </a>
        </div>
      </div>
    </>
  );
}
