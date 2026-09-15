"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronRight } from "./Icons.jsx";

/** True once the element has been scrolled into view. Fires once. */
export function useInView(threshold = 0.2) {
  const ref = useRef(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // IntersectionObserver rather than a scroll handler: a scroll listener
    // runs every frame and is the usual cause of a janky page.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { threshold }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [threshold]);

  return [ref, seen];
}

/**
 * A highlighter swipe behind one word.
 *
 * The stroke grows from the left when the heading enters view. Used once
 * per heading and never twice: a page where everything is highlighted has
 * highlighted nothing.
 */
export function Mark({ children, delay = 0 }) {
  const [ref, seen] = useInView(0.6);
  return (
    <span
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={`mark ${seen ? "" : "mark-hidden"}`}
    >
      {children}
    </span>
  );
}

export function Reveal({ children, delay = 0, className = "" }) {
  const [ref, seen] = useInView(0.15);
  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={`transition-[opacity,transform] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
        seen ? "opacity-100 translate-y-0" : "opacity-0 translate-y-3"
      } ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * A section with the vertical guide rules the reference runs down the page.
 * Decorative, so hidden from assistive technology.
 */
export function Section({ id, children, className = "" }) {
  return (
    <section id={id} className={`relative ${className}`}>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 left-[max(1.5rem,6vw)] hidden w-px dotted-y lg:block"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 right-[max(1.5rem,6vw)] hidden w-px dotted-y lg:block"
      />
      <div className="mx-auto w-full max-w-[1180px] px-6 sm:px-10 lg:px-16">
        {children}
      </div>
    </section>
  );
}

export function ButtonPrimary({ href, children }) {
  return (
    <a
      href={href}
      className="group inline-flex items-center gap-2 bg-marker px-5 py-2.5 text-[14px] font-medium text-ink-900 transition-colors hover:bg-marker-deep"
    >
      {children}
      <ChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
    </a>
  );
}

export function ButtonGhost({ href, children }) {
  return (
    <a
      href={href}
      className="group inline-flex items-center gap-2 px-2 py-2.5 text-[14px] font-medium text-ink-800 transition-colors hover:text-ink-900"
    >
      {children}
      <ChevronRight className="h-3.5 w-3.5 transition-transform duration-200 group-hover:translate-x-0.5" />
    </a>
  );
}

/** A headline figure with its unit and caption, as in the reference. */
export function Stat({ value, unit, label, caption, tone = "ink" }) {
  const color = tone === "marker" ? "text-marker-deep" : "text-ink-900";
  return (
    <div>
      <div className="text-[12.5px] text-ink-600">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-1.5">
        <span className={`text-[2rem] font-medium tabular-nums ${color}`}>
          {value}
        </span>
        {unit && <span className="text-[13px] text-ink-500">{unit}</span>}
      </div>
      {caption && (
        <div className="mt-1 text-[12.5px] text-ink-500">{caption}</div>
      )}
    </div>
  );
}
