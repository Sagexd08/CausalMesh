import { useEffect, useRef, useState } from "react";

/** Reveal on scroll, once. Respects prefers-reduced-motion via CSS. */
export function Reveal({ children, delay = 0, className = "" }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    // IntersectionObserver rather than a scroll handler: a scroll listener
    // runs on every frame and is the usual cause of janky marketing pages.
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { rootMargin: "-40px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      style={{ transitionDelay: `${delay}ms` }}
      className={`transition-[opacity,transform] duration-700 ease-[cubic-bezier(0.16,1,0.3,1)] ${
        shown ? "opacity-100 translate-y-0" : "opacity-0 translate-y-3"
      } ${className}`}
    >
      {children}
    </div>
  );
}

/** A section label. Mono, tracked, quiet — the page's structural rhythm. */
export function Eyebrow({ children, tone = "signal" }) {
  const color = tone === "signal" ? "text-signal-dim" : "text-chalk-600";
  return (
    <div className={`font-mono text-[11px] uppercase tracking-[0.18em] ${color}`}>
      {children}
    </div>
  );
}

export function Section({ id, children, className = "" }) {
  return (
    <section id={id} className={`relative px-6 md:px-10 lg:px-16 ${className}`}>
      <div className="mx-auto w-full max-w-[1180px]">{children}</div>
    </section>
  );
}

/** A number with its unit, monospaced so columns align at a glance. */
export function Stat({ value, unit, label, tone = "chalk" }) {
  const color = tone === "signal" ? "text-signal" : "text-chalk-100";
  return (
    <div>
      <div className={`font-mono text-3xl md:text-4xl tabular-nums ${color}`}>
        {value}
        {unit && <span className="text-chalk-600 text-xl ml-1">{unit}</span>}
      </div>
      <div className="mt-1.5 text-[13px] text-chalk-500">{label}</div>
    </div>
  );
}
