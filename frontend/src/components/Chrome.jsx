import { useEffect, useState } from "react";
import { Section } from "./Primitives.jsx";

const LINKS = [
  ["Problem", "#problem"],
  ["Question", "#question"],
  ["Results", "#results"],
  ["Architecture", "#architecture"],
  ["Evidence", "#integrity"],
];

export function Nav() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      {/* Skip link: the first tab stop must escape the nav, or a keyboard
          user re-traverses it on every page. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-signal focus:px-4 focus:py-2 focus:text-[14px] focus:text-ink-950"
      >
        Skip to content
      </a>

      <header
        className={`fixed inset-x-0 top-0 z-40 transition-colors duration-300 ${
          scrolled
            ? "border-b border-white/[0.07] bg-ink-950/85 backdrop-blur-md"
            : "border-b border-transparent"
        }`}
      >
        <nav
          aria-label="Primary"
          className="mx-auto flex h-16 w-full max-w-[1180px] items-center justify-between px-6 md:px-10 lg:px-16"
        >
          <a
            href="#main"
            className="flex items-baseline gap-2 text-[15px] font-medium tracking-tight text-chalk-100"
          >
            <span
              className="h-2 w-2 rounded-[2px] bg-signal"
              aria-hidden="true"
            />
            CausalMesh
          </a>

          <ul className="hidden items-center gap-8 md:flex">
            {LINKS.map(([label, href]) => (
              <li key={href}>
                <a
                  href={href}
                  className="text-[13.5px] text-chalk-500 transition-colors hover:text-chalk-200"
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>

          <a
            href="https://github.com/Sagexd08/CausalMesh"
            className="rounded-md border border-white/10 px-3.5 py-1.5 text-[13px] text-chalk-300 transition-colors hover:border-white/20 hover:text-chalk-100"
          >
            GitHub
          </a>
        </nav>
      </header>
    </>
  );
}

export function Footer() {
  return (
    <footer className="border-t border-white/[0.07] py-14">
      <Section>
        <div className="flex flex-col justify-between gap-8 md:flex-row md:items-end">
          <div className="max-w-prose">
            <div className="flex items-baseline gap-2 text-[15px] font-medium text-chalk-100">
              <span
                className="h-2 w-2 rounded-[2px] bg-signal"
                aria-hidden="true"
              />
              CausalMesh
            </div>
            <p className="mt-4 text-[14px] leading-relaxed text-chalk-500">
              A coordination substrate for fleets of autonomous coding agents,
              with cryptographically verifiable evidence of everything every
              agent did.
            </p>
            <p className="mt-4 font-mono text-[12px] leading-relaxed text-chalk-600">
              No hosted model has been run yet, and the analysis layer is not
              built. Every gap is tracked in docs/backlog.md with its reason.
            </p>
          </div>

          <div className="flex gap-10">
            <div>
              <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-chalk-600">
                Source
              </div>
              <ul className="mt-3 space-y-2">
                {[
                  ["Repository", "https://github.com/Sagexd08/CausalMesh"],
                  ["MIT licence", "https://github.com/Sagexd08/CausalMesh"],
                ].map(([label, href]) => (
                  <li key={label}>
                    <a
                      href={href}
                      className="text-[14px] text-chalk-400 transition-colors hover:text-chalk-100"
                    >
                      {label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      </Section>
    </footer>
  );
}
