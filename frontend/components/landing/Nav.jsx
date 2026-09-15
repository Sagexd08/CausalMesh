"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ChevronDown, MenuToggle } from "./Icons.jsx";
import { ButtonPrimary } from "./Primitives.jsx";

/**
 * Three destinations, plus the source.
 *
 * The bar carried eight items at one level, several of which meant the same
 * thing to a reader who had not already read the page: "Framework", "How it
 * works" and "Experiment" are three names for the same subject, and
 * "Results" appeared both in the bar and inside the Experiment menu.
 *
 * It is grouped now by the question a visitor is actually asking, in the
 * order they ask it: what is this, does it work, how do I use it. Each
 * group's own trigger goes to the best answer, and the menu under it lists
 * the rest. The count is what changed; nothing became unreachable.
 */
const NAV = [
  {
    label: "Product",
    href: "#framework",
    items: [
      ["The framework", "#framework"],
      ["How it works", "#architecture"],
      ["What it costs", "#calculator"],
      ["Works with your agent", "#agents"],
    ],
  },
  {
    label: "Research",
    href: "#question",
    items: [
      ["The question", "#question"],
      ["Measured results", "#results"],
      ["Evidence model", "#integrity"],
      ["Whitepaper", "/whitepaper"],
    ],
  },
  { label: "Docs", href: "/docs" },
];

/**
 * Resolve a section anchor against the page it is being rendered on.
 *
 * The nav is shared by `/` and `/whitepaper`, and a bare `#architecture`
 * scrolls to nothing on a page that has no such section. Prefixing with `/`
 * when away from the landing page sends the reader home and then to the
 * section, which is what the label promised.
 */
function resolve(href, onLanding) {
  return href.startsWith("#") && !onLanding ? `/${href}` : href;
}

/** The wordmark is text. No logo — the name is the mark. */
function Wordmark({ onLanding = true }) {
  return (
    <a href={onLanding ? "#main" : "/"} className="flex items-baseline gap-2">
      <span className="text-[19px] font-semibold tracking-tightest text-ink-900">
        CausalMesh
      </span>
      <span className="hidden text-[12px] text-ink-500 lg:inline">
        coordination substrate
      </span>
    </a>
  );
}

export default function Nav() {
  const [open, setOpen] = useState(null);
  const [menu, setMenu] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  const pathname = usePathname();
  const onLanding = pathname === "/";

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
          {/* Wordmark and nav are one left-hand cluster. As three separate
              children of a justify-between row, the links floated in the
              middle of the gap and read as unanchored. */}
          <div className="flex items-center gap-8">
            <Wordmark onLanding={onLanding} />

            <ul className="hidden items-center gap-1 lg:flex">
            {NAV.map((entry) => (
              <li
                key={entry.label}
                className="relative"
                onMouseEnter={() => entry.items && setOpen(entry.label)}
                onMouseLeave={() => setOpen(null)}
              >
                <a
                  href={resolve(entry.href, onLanding)}
                  className="inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-[14px] text-ink-700 transition-colors hover:bg-paper-sunk hover:text-ink-900"
                  aria-expanded={entry.items ? open === entry.label : undefined}
                >
                  {entry.label}
                  {entry.items && (
                    <ChevronDown className="h-3 w-3 text-ink-400" />
                  )}
                </a>

                {entry.items && open === entry.label && (
                  <ul className="absolute left-0 top-full z-30 w-52 overflow-hidden rounded-lg border border-rule-soft bg-paper py-1 shadow-[0_16px_40px_-24px_rgb(16_16_16_/_0.4)]">
                    {entry.items.map(([label, href]) => (
                      <li key={label}>
                        <a
                          href={resolve(href, onLanding)}
                          className="block px-4 py-2 text-[13.5px] text-ink-700 transition-colors hover:bg-paper-sunk hover:text-ink-900"
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
          </div>

          <div className="flex items-center gap-2">
            {/* One action. "Results" used to sit here and now lives in the
                Research menu, where a reader looking for it will already be. */}
            <ButtonPrimary href="https://github.com/Sagexd08/CausalMesh">
              Get the source
            </ButtonPrimary>

            {/* Below lg the links are hidden, and until now nothing replaced
                them: every section was unreachable on a phone. */}
            <button
              type="button"
              onClick={() => setMenu((value) => !value)}
              aria-expanded={menu}
              aria-controls="cm-mobile-nav"
              aria-label={menu ? "Close menu" : "Open menu"}
              className="-mr-2 inline-flex h-11 w-11 items-center justify-center rounded-md text-ink-700 transition-colors hover:bg-paper-sunk hover:text-ink-900 lg:hidden"
            >
              <MenuToggle open={menu} />
            </button>
          </div>
        </nav>

        {/* The mobile panel. Flat and grouped rather than nested and
            collapsible: with three groups and eleven destinations there is
            nothing to save by hiding half of them behind another tap. */}
        {menu && (
          <div
            id="cm-mobile-nav"
            className="border-t border-rule-soft bg-paper lg:hidden"
          >
            <div className="mx-auto w-full max-w-[1180px] px-6 py-5 sm:px-10">
              {NAV.map((entry) => (
                <div key={entry.label} className="border-b border-rule-soft py-4 last:border-0">
                  <a
                    href={resolve(entry.href, onLanding)}
                    onClick={() => setMenu(false)}
                    className="flex min-h-11 items-center text-[15px] font-medium text-ink-900"
                  >
                    {entry.label}
                  </a>
                  {entry.items && (
                    <ul className="mt-2.5 space-y-0.5">
                      {entry.items.map(([label, href]) => (
                        <li key={label}>
                          <a
                            href={resolve(href, onLanding)}
                            onClick={() => setMenu(false)}
                            className="flex min-h-11 items-center text-[14px] text-ink-600 transition-colors hover:text-ink-900"
                          >
                            {label}
                          </a>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </header>
    </>
  );
}
