// frontend/components/landing/DecisionLoop.jsx
"use client";

import { useEffect, useState } from "react";
import { Mark, Section, useInView } from "./Primitives.jsx";

/**
 * The decision loop: four typed questions a run asks as it progresses.
 *
 * This section exists because Framework.jsx already establishes the four
 * planes — contract, enforcement, evidence, measurement — as a single
 * allow/refuse check. This section is about what does *not* fit a single
 * check: a run also has to classify its task, pick an agent, decide how to
 * recover from a failure, and decide whether the result is acceptable.
 * Those are a small, fixed set of typed questions, which is exactly the
 * shape TypeSafe AI's Jev answers (state in, a typed Choice/Score/Noul
 * question out, a calibrated probability back — never a generated answer
 * outside the options given).
 *
 * Honesty, matching Framework.jsx's own discipline: the Jev adapter is
 * built and tested against the real API. None of these four decisions are
 * wired into the runtime yet, and the copy says so rather than implying a
 * working decision loop exists.
 */

const DECISIONS = [
  {
    id: "classify",
    label: "classify",
    question: "What kind of task is this?",
  },
  {
    id: "select_agent",
    label: "select_agent",
    question: "Which agent should act next?",
  },
  {
    id: "recover",
    label: "recover",
    question: "After a failure: retry, switch agent, or escalate?",
  },
  {
    id: "accept",
    label: "accept",
    question: "Does the evidence support ACCEPT, REJECT, or HUMAN_REVIEW?",
  },
];

function StatusPill() {
  return (
    <span className="ml-auto shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] text-ink-600 bg-paper-sunk border-rule-soft">
      Planned
    </span>
  );
}

export default function DecisionLoop() {
  const [ref, seen] = useInView(0.3);
  const [step, setStep] = useState(0);

  useEffect(() => {
    if (!seen) return;
    const reduced = window.matchMedia?.(
      "(prefers-reduced-motion: reduce)"
    )?.matches;
    if (reduced) {
      setStep(DECISIONS.length);
      return;
    }
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      setStep(n);
      if (n >= DECISIONS.length) clearInterval(timer);
    }, 600);
    return () => clearInterval(timer);
  }, [seen]);

  return (
    <Section id="decision-loop" className="py-24 md:py-32">
      <div className="grid grid-cols-1 items-center gap-x-16 gap-y-14 lg:grid-cols-[1fr_1.15fr]">
        <div>
          <h2 className="font-display text-[clamp(2.1rem,1.873rem+0.909vw,2.6rem)] font-bold leading-[1.1] tracking-tightest text-ink-900">
            One gate check,
            <br />
            or a <Mark>decision loop</Mark>
          </h2>

          <p className="mt-6 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            The gate answers one question: allow or refuse. A run also has
            to classify its task, pick an agent, decide how to recover from
            a failure, and decide whether the result is acceptable — four
            typed questions asked repeatedly as the run progresses, not
            once.
          </p>

          <p className="mt-4 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            TypeSafe AI&rsquo;s Jev answers exactly this shape of question:
            state in, a typed choice, score, or yes/no out, by selection
            rather than generation. We built and tested a Jev client
            against the real API to confirm the shape is implementable
            cheaply today.
          </p>

          <p className="mt-5 text-[13px] leading-relaxed text-ink-500">
            The adapter is real and tested. None of the four decisions below
            are wired into a run yet — see{" "}
            <a
              href="/docs"
              className="text-ink-700 underline decoration-rule-soft underline-offset-2 hover:text-ink-900"
            >
              the docs
            </a>{" "}
            for what that would take.
          </p>
        </div>

        <div ref={ref} className="flex flex-col gap-2.5">
          {DECISIONS.map((decision, i) => {
            const shown = i < step;
            return (
              <div
                key={decision.id}
                className={`flex items-center gap-3.5 border px-4 py-3.5 transition-all duration-500 ${
                  shown
                    ? "translate-x-0 opacity-100 border-rule-soft bg-paper-raised"
                    : "-translate-x-2 opacity-0 border-rule-soft bg-paper-raised"
                }`}
              >
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-rule-soft font-mono text-[11px] tabular-nums text-ink-600">
                  {i + 1}
                </span>
                <div className="min-w-0">
                  <div className="font-mono text-[13px] text-ink-900">
                    {decision.label}
                  </div>
                  <div className="mt-0.5 truncate text-[12.5px] text-ink-500">
                    {decision.question}
                  </div>
                </div>
                <StatusPill />
              </div>
            );
          })}
        </div>
      </div>
    </Section>
  );
}
