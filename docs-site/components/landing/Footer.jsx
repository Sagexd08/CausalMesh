import agentMarks from "@/lib/landing/agent-marks.json";
import { Check } from "./Icons.jsx";

/**
 * Compact structured footer, in the shape of the reference: wordmark and
 * legal on the left, link columns on the right, credential chips, then a
 * thin bottom rule.
 *
 * The reference's chips say "Backed by Y Combinator" and "SOC 2". This
 * project has neither, and inventing them would be a fabricated
 * endorsement. The chips carry what is actually true and checkable — the
 * test count, the licence, the verification property — which is the same
 * shape of claim without the lie.
 */

const COLUMNS = [
  [
    "Experiment",
    [
      ["The question", "#question"],
      ["Routing", "#routing"],
      ["Results", "#results"],
      ["Evidence", "#integrity"],
    ],
  ],
  [
    "Platform",
    [
      ["How it works", "#architecture"],
      ["Agents", "#agents"],
      ["Tool boundary", "#architecture"],
      ["Claim registry", "#routing"],
    ],
  ],
  [
    "Project",
    [
      ["Repository", "https://github.com/Sagexd08/CausalMesh"],
      [
        "Security model",
        "https://github.com/Sagexd08/CausalMesh/blob/main/docs/security.md",
      ],
      [
        "Model adapters",
        "https://github.com/Sagexd08/CausalMesh/blob/main/docs/adapters.md",
      ],
      [
        "Known gaps",
        "https://github.com/Sagexd08/CausalMesh/blob/main/docs/backlog.md",
      ],
    ],
  ],
];

const CHIPS = [
  ["Test suite", "839 passing"],
  ["Licence", "MIT"],
  ["Evidence", "Verifies offline"],
];

const BOTTOM = [
  ["No fabricated results", "#results"],
  ["Raw data is immutable", "#integrity"],
  ["Limitations documented", "https://github.com/Sagexd08/CausalMesh/blob/main/docs/backlog.md"],
];

function GitHubMark({ className = "h-4 w-4" }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className={className} aria-hidden="true">
      <path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.36 1.09 2.94.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.5 9.5 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 12 2Z" />
    </svg>
  );
}

export default function Footer() {
  return (
    <footer className="border-t border-rule-soft">
      <div className="mx-auto w-full max-w-[1180px] px-6 py-14 sm:px-10 lg:px-16">
        <div className="grid grid-cols-1 gap-x-12 gap-y-12 lg:grid-cols-[1.1fr_2fr]">
          <div>
            <div className="text-[19px] font-semibold tracking-tightest text-ink-900">
              CausalMesh
            </div>
            <p className="mt-3 max-w-[34ch] text-[13.5px] leading-relaxed text-ink-600">
              A coordination substrate for fleets of autonomous coding agents,
              with cryptographically verifiable evidence of everything every
              agent did.
            </p>

            <a
              href="https://github.com/Sagexd08/CausalMesh"
              className="mt-5 inline-flex items-center gap-2 rounded-md border border-rule-soft px-3 py-2 text-[13px] text-ink-700 transition-colors hover:border-ink-900 hover:text-ink-900"
            >
              <GitHubMark />
              Source on GitHub
            </a>

            <div className="mt-6 flex flex-wrap gap-2">
              {CHIPS.map(([label, value]) => (
                <div
                  key={label}
                  className="rounded-md border border-rule-soft px-3 py-2"
                >
                  <div className="text-[10.5px] uppercase tracking-[0.1em] text-ink-400">
                    {label}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[12.5px] font-medium text-ink-900">
                    <Check className="h-3 w-3 text-marker-deep" />
                    {value}
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-8 gap-y-10 sm:grid-cols-3">
            {COLUMNS.map(([heading, links]) => (
              <nav key={heading} aria-label={heading}>
                <h2 className="text-[12.5px] font-medium text-ink-900">
                  {heading}
                </h2>
                <ul className="mt-3.5 space-y-2.5">
                  {links.map(([label, href]) => (
                    <li key={label}>
                      <a
                        href={href}
                        className="text-[13.5px] text-ink-600 transition-colors hover:text-ink-900"
                      >
                        {label}
                      </a>
                    </li>
                  ))}
                </ul>
              </nav>
            ))}
          </div>
        </div>

        {/* Agents the substrate can drive, as marks. */}
        <div className="mt-14 border-t border-rule-soft pt-8">
          <div className="text-[12.5px] text-ink-500">
            Drives any OpenAI-compatible client
          </div>
          <ul className="mt-4 flex flex-wrap items-center gap-x-7 gap-y-4">
            {agentMarks.map(({ name, src }) => (
              <li
                key={name}
                className="group flex items-center gap-2 text-ink-400 transition-colors hover:text-ink-900"
              >
                <img
                  src={src}
                  alt=""
                  aria-hidden="true"
                  className="h-[18px] w-[18px] object-contain opacity-75 grayscale transition-all group-hover:opacity-100 group-hover:grayscale-0"
                />
                <span className="text-[13px] text-ink-600 transition-colors group-hover:text-ink-900">
                  {name}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-10 flex flex-col-reverse items-start justify-between gap-5 border-t border-rule-soft pt-6 sm:flex-row sm:items-center">
          <p className="text-[12.5px] text-ink-500">
            MIT licence &middot; Python 3.11+ &middot; no telemetry
          </p>
          <nav aria-label="Commitments">
            <ul className="flex flex-wrap gap-x-7 gap-y-2">
              {BOTTOM.map(([label, href]) => (
                <li key={label}>
                  <a
                    href={href}
                    className="text-[12.5px] text-ink-500 transition-colors hover:text-ink-900"
                  >
                    {label}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </div>
      </div>
    </footer>
  );
}
