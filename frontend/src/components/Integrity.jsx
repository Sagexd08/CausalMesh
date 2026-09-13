import { Mark, Reveal, Section } from "./Primitives.jsx";

const ATTACKS = [
  ["Event mutation", true],
  ["Event insertion", true],
  ["Event deletion", true],
  ["Event reordering", true],
  ["Signature substitution", true],
  ["Wrong-actor attribution", true],
  ["Duplicate replay", true],
  ["Suffix truncation", false],
];

export default function Integrity() {
  return (
    <Section id="integrity" className="py-24 md:py-32">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-12 gap-y-14">
        <div className="lg:col-span-5">
          <h2 className="font-display text-3xl md:text-[2.6rem] leading-[1.08] font-bold tracking-tightest text-ink-900">
            What the chain
            <br />
            actually <Mark>detects</Mark>
          </h2>
          <p className="mt-7 max-w-prose text-[16px] leading-relaxed text-ink-600">
            An adversarial battery attacks the log and requires the verifier to
            catch it. The results are the honest scope of the integrity claim —
            including the row that fails.
          </p>
          <p className="mt-5 max-w-prose text-[15px] leading-relaxed text-ink-600">
            Truncating the end of a chain is undetectable from the chain alone,
            because a shorter valid chain is still a valid chain. With a
            published anchor it is caught. That limitation is documented rather
            than omitted, and it is tested in both directions.
          </p>
        </div>

        <div className="lg:col-span-7 lg:pt-4">
          <ul className="divide-y divide-rule-soft border-y border-rule-soft">
            {ATTACKS.map(([name, detected], i) => (
              <Reveal key={name} delay={i * 40}>
                <li className="flex items-center justify-between gap-6 py-4">
                  <span className="text-[15px] text-ink-700">{name}</span>
                  {detected ? (
                    <span className="flex items-center gap-2 font-mono text-[12px] text-marker-deep">
                      <span
                        className="h-1.5 w-1.5 rounded-full bg-marker-deep"
                        aria-hidden="true"
                      />
                      detected
                    </span>
                  ) : (
                    <span className="text-right font-mono text-[12px] leading-tight text-arm-c3">
                      needs an anchor
                      <span className="block text-ink-500">
                        undetected without one
                      </span>
                    </span>
                  )}
                </li>
              </Reveal>
            ))}
          </ul>
        </div>
      </div>
    </Section>
  );
}
