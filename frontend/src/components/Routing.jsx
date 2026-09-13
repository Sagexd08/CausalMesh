import { useEffect, useState } from "react";
import { Mark, Section, useInView } from "./Primitives.jsx";

/**
 * The write-gate diagram: five write attempts, one contested file.
 *
 * This is the C3 mechanism drawn rather than described. Four writes go to
 * files their agent owns and are granted; the fifth targets a file another
 * agent holds a lease on, and is refused with the holder named.
 *
 * The shape is taken from the reference's routing diagram, but the content
 * is this system's: the numbers match the concurrent_edit_collision run in
 * data/raw/pilot_landing, where C3 recorded exactly one denial.
 */

const WRITES = [
  { id: 1, agent: "agent_a", target: "src/alpha.py", state: "granted", to: 0 },
  { id: 2, agent: "agent_a", target: "src/config.py", state: "granted", to: 1 },
  { id: 3, agent: "agent_b", target: "src/beta.py", state: "granted", to: 2 },
  { id: 4, agent: "agent_b", target: "src/config.py", state: "denied", to: 1 },
  { id: 5, agent: "agent_a", target: "src/config.py", state: "granted", to: 1 },
];

const FILES = [
  { name: "src/alpha.py", holder: "agent_a" },
  { name: "src/config.py", holder: "agent_a", contested: true },
  { name: "src/beta.py", holder: "agent_b" },
];

export default function Routing() {
  const [ref, seen] = useInView(0.3);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!seen) return;
    const reduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)"
    )?.matches;
    if (reduced) {
      setStep(WRITES.length);
      return;
    }
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      setStep(n);
      if (n >= WRITES.length) clearInterval(timer);
    }, 700);
    return () => clearInterval(timer);
  }, [seen]);

  return (
    <Section id="routing" className="py-24 md:py-32">
      <div className="grid grid-cols-1 items-center gap-x-16 gap-y-14 lg:grid-cols-[1.15fr_1fr]">
        {/* Diagram */}
        <div ref={ref}>
          <div className="mb-5 text-[13px] text-ink-600">
            five write attempts, one contested file
          </div>

          <div className="relative grid grid-cols-[1fr_auto_1fr] items-center gap-x-4 sm:gap-x-8">
            <ul className="space-y-2.5">
              {WRITES.map((w, i) => {
                const shown = i < step;
                const denied = w.state === "denied";
                return (
                  <li
                    key={w.id}
                    className={`flex items-center justify-between gap-3 border px-3 py-2.5 transition-all duration-500 ${
                      shown
                        ? "translate-x-0 opacity-100"
                        : "-translate-x-2 opacity-0"
                    } ${
                      denied && shown
                        ? "border-arm-c0 bg-arm-c0/[0.06]"
                        : "border-rule-soft bg-paper-raised"
                    }`}
                  >
                    <span className="font-mono text-[12.5px] text-ink-700">
                      write {w.id}
                    </span>
                    <span
                      className={`font-mono text-[11px] uppercase tracking-wide ${
                        denied ? "text-arm-c0" : "text-marker-deep"
                      }`}
                    >
                      {shown ? (denied ? "denied" : "ok") : ""}
                    </span>
                  </li>
                );
              })}
            </ul>

            {/* Connectors */}
            <svg
              viewBox="0 0 100 220"
              preserveAspectRatio="none"
              className="h-[236px] w-14 sm:w-20"
              aria-hidden="true"
            >
              {WRITES.map((w, i) => {
                const shown = i < step;
                const y1 = 22 + i * 43;
                const y2 = 40 + w.to * 68;
                const denied = w.state === "denied";
                return (
                  <path
                    key={w.id}
                    d={`M0 ${y1} C 45 ${y1}, 55 ${y2}, 100 ${y2}`}
                    fill="none"
                    stroke={denied ? "#c2410c" : "#6fbe0f"}
                    strokeWidth="1.4"
                    strokeDasharray={denied ? "4 3" : "none"}
                    className="transition-opacity duration-500"
                    opacity={shown ? (denied ? 0.9 : 0.75) : 0}
                  />
                );
              })}
            </svg>

            <ul className="space-y-4">
              {FILES.map((f, i) => {
                const isContested = f.contested;
                const lit = step >= 2 && isContested;
                return (
                  <li
                    key={f.name}
                    className={`border px-3 py-3 transition-all duration-500 ${
                      lit
                        ? "border-marker-deep bg-marker/10"
                        : "border-rule-soft bg-paper-raised"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate font-mono text-[12px] text-ink-800">
                        {f.name}
                      </span>
                      {lit && (
                        <span className="shrink-0 font-mono text-[10px] uppercase tracking-wide text-marker-deep">
                          lease
                        </span>
                      )}
                    </div>
                    <div className="mt-1 font-mono text-[10.5px] text-ink-500">
                      held by {f.holder}
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          <p className="mt-6 text-[13px] text-ink-500">
            Without enforcement, write 4 lands and agent_a&rsquo;s work is
            gone.
          </p>
        </div>

        {/* Copy */}
        <div>
          <h2 className="font-display text-[2.1rem] font-bold leading-[1.1] tracking-tightest text-ink-900 sm:text-[2.6rem]">
            One path,
            <br />
            one <Mark>writer</Mark>
          </h2>

          <p className="mt-6 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            A transactional lease registry keeps concurrent agents off each
            other&rsquo;s files.
          </p>

          <dl className="mt-9 space-y-7">
            {[
              [
                "At most one writer per path.",
                "SQLite with BEGIN IMMEDIATE, so check-and-acquire is a single atomic step rather than a race two agents can both win.",
              ],
              [
                "Leases expire.",
                "A crashed agent cannot wedge the fleet. Expiry and release are recorded distinctly, because “too slow” and “finished” are different signals.",
              ],
              [
                "Refusals are data.",
                "Every denial records the requesting agent, the path, the holder, and the reason — so a blocked write is explainable months later.",
              ],
            ].map(([term, detail]) => (
              <div
                key={term}
                className="border-t border-rule-soft pt-5 first:border-t-0 first:pt-0"
              >
                <dt className="text-[17px] font-medium text-ink-900">{term}</dt>
                <dd className="mt-1.5 max-w-prose text-[14.5px] leading-relaxed text-ink-600">
                  {detail}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </div>
    </Section>
  );
}
