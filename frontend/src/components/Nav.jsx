import { useEffect, useState } from "react";
import { ChevronDown } from "./Icons.jsx";
import { ButtonPrimary } from "./Primitives.jsx";

const NAV = [
  { label: "How it works", href: "#architecture" },
  {
    label: "Experiment",
    href: "#question",
    items: [
      ["The question", "#question"],
      ["Routing", "#routing"],
      ["Results", "#results"],
    ],
  },
  { label: "Evidence", href: "#integrity" },
  { label: "Docs", href: "/docs" },
];

/** The wordmark is text. No logo — the name is the mark. */
function Wordmark() {
  return (
    <a href="#main" className="flex items-baseline gap-2">
      <span className="text-[19px] font-semibold tracking-tightest text-ink-900">
        CausalMesh
      </span>
      <span className="hidden text-[12px] text-ink-500 sm:inline">
        coordination substrate
      </span>
    </a>
  );
}

export default function Nav() {
  const [open, setOpen] = useState(null);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <>
      {/* The first tab stop must escape the nav, or a keyboard user
          re-traverses it on every page. */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:bg-ink-900 focus:px-4 focus:py-2 focus:text-[14px] focus:text-paper"
      >
        Skip to content
      </a>

      <header
        className={`sticky top-0 z-40 border-b transition-colors duration-300 ${
          scrolled
            ? "border-rule-soft bg-paper/90 backdrop-blur-md"
            : "border-transparent bg-paper"
        }`}
      >
        <nav
          aria-label="Primary"
          className="mx-auto flex h-16 w-full max-w-[1180px] items-center justify-between gap-6 px-6 sm:px-10 lg:px-16"
        >
          <Wordmark />

          <ul className="hidden items-center gap-7 lg:flex">
            {NAV.map((entry) => (
              <li
                key={entry.label}
                className="relative"
                onMouseEnter={() => entry.items && setOpen(entry.label)}
                onMouseLeave={() => setOpen(null)}
              >
                <a
                  href={entry.href}
                  className="inline-flex items-center gap-1 py-2 text-[14px] text-ink-700 transition-colors hover:text-ink-900"
                  aria-expanded={entry.items ? open === entry.label : undefined}
                >
                  {entry.label}
                  {entry.items && (
                    <ChevronDown className="h-3 w-3 text-ink-400" />
                  )}
                </a>

                {entry.items && open === entry.label && (
                  <ul className="absolute left-0 top-full z-30 w-44 border border-rule-soft bg-paper py-1 shadow-[0_12px_28px_-16px_rgba(16,16,16,0.35)]">
                    {entry.items.map(([label, href]) => (
                      <li key={label}>
                        <a
                          href={href}
                          className="block px-3.5 py-2 text-[13.5px] text-ink-700 transition-colors hover:bg-paper-sunk hover:text-ink-900"
                        >
                          {label}
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>

          <div className="flex items-center gap-3">
            <a
              href="#results"
              className="hidden text-[14px] text-ink-700 transition-colors hover:text-ink-900 sm:inline"
            >
              Results
            </a>
            <ButtonPrimary href="https://github.com/Sagexd08/CausalMesh">
              Get the source
            </ButtonPrimary>
          </div>
        </nav>
      </header>
    </>
  );
}
