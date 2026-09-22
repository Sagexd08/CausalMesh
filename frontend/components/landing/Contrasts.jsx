import { CONTRASTS } from "@/lib/landing/data.js";
import { Mark, Reveal, Section } from "./Primitives.jsx";

export default function Contrasts() {
  return (
    <Section id="question" className="py-24 md:py-32">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-12 gap-y-14">
        <div className="lg:col-span-6">
          <h2 className="font-display text-[clamp(1.875rem,1.545rem+1.318vw,2.6rem)] leading-[1.08] font-bold tracking-tightest text-ink-900">
            Information, or
            <br />
            <Mark>enforcement</Mark>?
          </h2>
          <p className="mt-7 max-w-prose text-[16px] leading-relaxed text-ink-600">
            Systems that share state also lock it. The two arrive together, so
            nobody knows which one is doing the work — and they cost very
            different things.
          </p>
          <p className="mt-5 max-w-prose text-[16px] leading-relaxed text-ink-600">
            Enforcement needs a consistent lock store: latency, a failure
            domain, and contention when agents genuinely need the same file.
            Information needs context tokens. If information alone recovers most
            of the benefit, you can run a much cheaper and more available
            system.
          </p>
          <p className="mt-5 max-w-prose text-[16px] leading-relaxed text-ink-600">
            These are not academic conditions. They are the four deployment
            configurations you can actually choose.
          </p>
        </div>

        <div className="lg:col-span-6 lg:pt-6">
          <ul className="space-y-px overflow-hidden rounded-lg border border-rule-soft bg-rule-soft">
            {CONTRASTS.map((c, i) => (
              <Reveal key={c.pair} delay={i * 60}>
                <li className="flex items-center justify-between gap-6 bg-paper-raised px-6 py-5">
                  <span className="font-mono text-[15px] text-ink-800">
                    {c.pair}
                  </span>
                  <span className="flex items-center gap-3 text-right">
                    <span className="text-[14px] text-ink-600">
                      {c.isolates}
                    </span>
                    {c.confounded && (
                      <span className="rounded border border-arm-c0/40 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-arm-c0">
                        confounded
                      </span>
                    )}
                  </span>
                </li>
              </Reveal>
            ))}
          </ul>
          <p className="mt-5 max-w-prose text-[14px] leading-relaxed text-ink-500">
            The last comparison varies both factors at once. It is reported as
            the end-to-end effect of a complete system, never as evidence for
            either factor alone — and a test asserts that each of the other
            three really does vary exactly one.
          </p>
        </div>
      </div>
    </Section>
  );
}
