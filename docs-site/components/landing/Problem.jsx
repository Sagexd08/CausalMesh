import { Mark, Reveal, Section } from "./Primitives.jsx";
import { FAILURES } from "@/lib/landing/data.js";

export default function Problem() {
  return (
    <Section id="problem" className="py-24 md:py-32">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-12 gap-y-12">
        <div className="lg:col-span-5">
          <h2 className="font-display text-3xl md:text-[2.6rem] leading-[1.08] font-bold tracking-tightest text-ink-900">
            Agents don&apos;t fail alone.
            <br />
            They fail on <Mark>each other</Mark>
          </h2>
          <p className="mt-7 max-w-prose text-[16px] leading-relaxed text-ink-600">
            Every failure below is a coordination failure, not a capability
            failure. Each agent is doing competent work. The system is what
            loses.
          </p>
          <p className="mt-5 max-w-prose text-[16px] leading-relaxed text-ink-600">
            Git resolves textual conflicts on the same lines. It has nothing to
            say about a schema and its handler drifting apart with no
            overlapping edit — and no lock system tells you{" "}
            <em className="not-italic text-ink-700">why</em> a write was
            refused, six hours later, in an audit.
          </p>
        </div>

        <div className="lg:col-span-7 lg:pt-16">
          <ul className="divide-y divide-rule-soft border-y border-rule-soft">
            {FAILURES.map((failure, i) => (
              <Reveal key={failure.name} delay={i * 70}>
                <li className="group grid grid-cols-[2.2rem_1fr] gap-x-4 py-6">
                  <span className="font-mono text-[11px] tabular-nums text-ink-500 pt-1">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3 className="text-[17px] font-medium text-ink-900">
                      {failure.name}
                    </h3>
                    <p className="mt-1.5 max-w-prose text-[15px] leading-relaxed text-ink-600">
                      {failure.detail}
                    </p>
                  </div>
                </li>
              </Reveal>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}
