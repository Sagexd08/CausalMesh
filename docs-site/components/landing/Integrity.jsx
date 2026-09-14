import { Mark, Reveal, Section } from "./Primitives.jsx";

const DETECTED_ATTACKS = [
  "Event mutation",
  "Event insertion",
  "Event deletion",
  "Event reordering",
  "Signature substitution",
  "Wrong-actor attribution",
  "Duplicate replay",
];

function DetectedStatus() {
  return (
    <span className="flex shrink-0 items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-marker-deep">
      <span className="h-1.5 w-1.5 bg-marker-deep" aria-hidden="true" />
      detected
    </span>
  );
}

export default function Integrity() {
  return (
    <Section id="integrity" className="py-24 md:py-32">
      <div className="grid grid-cols-1 gap-x-12 gap-y-14 lg:grid-cols-12">
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
            Truncating the end of a chain is undetectable from the chain alone:
            a shorter, internally valid chain is still valid. A published
            anchor changes that result. The limitation is documented rather
            than omitted, and tested in both directions.
          </p>
          <div className="mt-9 max-w-prose border-l-2 border-marker pl-4">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-500">
              What verification binds
            </p>
            <p className="mt-2 text-[13px] leading-relaxed text-ink-700">
              Canonical event data, hash-linked order, Ed25519 signatures tied
              to the key ring, and unique event IDs.
            </p>
          </div>
        </div>

        <article
          className="border border-rule-soft bg-paper-raised p-[5px] lg:col-span-7 lg:mt-1"
          aria-labelledby="integrity-ledger-title"
        >
          <div className="border border-rule-soft">
            <header className="flex flex-col gap-4 border-b border-rule-soft px-5 py-5 sm:flex-row sm:items-end sm:justify-between sm:px-6">
              <div>
                <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-ink-500">
                  Offline verification ledger
                </p>
                <h3
                  id="integrity-ledger-title"
                  className="mt-1.5 text-[17px] font-medium tracking-tight text-ink-900"
                >
                  Adversarial attack battery
                </h3>
              </div>
              <p className="font-mono text-[10px] uppercase tracking-[0.1em] text-marker-deep">
                7 tamper modes / detected
              </p>
            </header>

            <ol className="divide-y divide-rule-soft">
              {DETECTED_ATTACKS.map((name, index) => (
                <li key={name}>
                  <Reveal delay={index * 40}>
                    <div className="flex items-center justify-between gap-5 px-5 py-[15px] sm:px-6">
                      <span className="text-[14px] text-ink-700">{name}</span>
                      <DetectedStatus />
                    </div>
                  </Reveal>
                </li>
              ))}

              <li>
                <Reveal delay={DETECTED_ATTACKS.length * 40}>
                  <div className="bg-[#fffaf2] px-5 py-5 sm:px-6">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <p className="text-[14px] text-ink-800">Suffix truncation</p>
                        <p className="mt-1 text-[12px] leading-relaxed text-ink-600">
                          The chain alone cannot prove that its final records
                          were not removed.
                        </p>
                      </div>
                      <span className="shrink-0 font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-arm-c3">
                        needs external anchor
                      </span>
                    </div>

                    <dl className="mt-5 grid border-y border-[#eadbc2] sm:grid-cols-2">
                      <div className="border-b border-[#eadbc2] py-3 sm:border-b-0 sm:border-r sm:pr-5">
                        <dt className="font-mono text-[10px] uppercase tracking-[0.11em] text-ink-500">
                          Chain only
                        </dt>
                        <dd className="mt-1 flex items-baseline justify-between gap-3 text-[12px] text-ink-700">
                          <span>shorter valid chain</span>
                          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-arm-c3">
                            not detectable
                          </span>
                        </dd>
                      </div>
                      <div className="py-3 sm:pl-5">
                        <dt className="font-mono text-[10px] uppercase tracking-[0.11em] text-ink-500">
                          Published anchor
                        </dt>
                        <dd className="mt-1 flex items-baseline justify-between gap-3 text-[12px] text-ink-700">
                          <span>missing anchored head</span>
                          <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-marker-deep">
                            detected
                          </span>
                        </dd>
                      </div>
                    </dl>
                  </div>
                </Reveal>
              </li>
            </ol>
          </div>
        </article>
      </div>
    </Section>
  );
}
