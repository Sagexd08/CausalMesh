import { ARMS, armResult } from "../data.js";
import { Mark, Reveal, Section } from "./Primitives.jsx";

/**
 * What each arm actually costs, per run.
 *
 * The reference lays a measured value against a list price on one track per
 * row. Here the track runs from zero to the most expensive arm, with the
 * measured coordination cost marked on it — so C1's overhead against C2 is
 * a length you can see rather than a number you have to hold in your head.
 */

const NOTE = {
  C0: "nothing delivered, nothing injected",
  C1: "every peer event, in full",
  C2: "bounded window, scored selection",
  C3: "same channel object as C2",
};

export default function Cost() {
  const rows = ARMS.map((a) => ({ ...a, ...armResult(a.id) }));
  const max = Math.max(...rows.map((r) => r.mean_coordination_bytes), 1);
  const c1 = armResult("C1");
  const c2 = armResult("C2");
  const ratio = (c1.mean_coordination_bytes / c2.mean_coordination_bytes).toFixed(1);

  return (
    <Section id="results" className="py-24 md:py-32">
      <h2 className="max-w-[18ch] font-display text-[2.3rem] font-bold leading-[1.08] tracking-tightest text-ink-900 sm:text-[3rem]">
        What coordination <Mark>actually</Mark> costs
      </h2>
      <p className="mt-5 max-w-prose text-[15.5px] text-ink-600">
        Bytes entering an agent&rsquo;s context per run, at each arm&rsquo;s
        measured success rate. 24 runs, two tasks, one machine.
      </p>

      <div className="mt-14 space-y-0">
        <div className="hidden grid-cols-[190px_1fr_150px] gap-6 border-b border-rule-soft pb-3 md:grid">
          <span className="text-[12px] text-ink-500">Arm</span>
          <span className="text-[12px] text-ink-500">
            Coordination bytes per run
          </span>
          <span className="text-right text-[12px] text-ink-500">
            Runs passed
          </span>
        </div>

        {rows.map((row, i) => {
          const pct = (row.mean_coordination_bytes / max) * 100;
          const isFree = row.mean_coordination_bytes === 0;
          return (
            <Reveal key={row.id} delay={i * 80}>
              <div className="grid grid-cols-1 items-center gap-x-6 gap-y-3 border-b border-rule-soft py-7 md:grid-cols-[190px_1fr_150px]">
                <div>
                  <div className="flex items-baseline gap-2">
                    <span className="font-mono text-[14px] font-medium text-ink-900">
                      {row.id}
                    </span>
                    <span className="text-[15px] text-ink-800">{row.name}</span>
                  </div>
                  <div className="mt-1 text-[12.5px] text-ink-500">
                    {NOTE[row.id]}
                  </div>
                </div>

                <div className="relative">
                  <div className="relative h-px w-full bg-rule-soft">
                    <div
                      className="absolute inset-y-0 left-0 h-px bg-marker-deep transition-[width] duration-1000 ease-out"
                      style={{ width: `${Math.max(pct, 0.5)}%` }}
                    />
                    <span
                      className="absolute top-1/2 h-3 w-3 -translate-y-1/2 bg-marker-deep transition-[left] duration-1000 ease-out"
                      style={{ left: `calc(${Math.max(pct, 0.5)}% - 6px)` }}
                      aria-hidden="true"
                    />
                    {!isFree && (
                      <span
                        className="absolute top-1/2 h-3 w-3 -translate-y-1/2 bg-ink-300"
                        style={{ left: "calc(100% - 6px)" }}
                        aria-hidden="true"
                      />
                    )}
                  </div>
                  <div className="mt-3 flex items-baseline justify-between">
                    <span className="font-mono text-[12.5px] text-ink-700">
                      {row.mean_coordination_bytes} B
                    </span>
                    {!isFree && row.mean_coordination_bytes < max && (
                      <span className="font-mono text-[12px] text-ink-400">
                        transcript {max} B
                      </span>
                    )}
                  </div>
                </div>

                <div className="text-left md:text-right">
                  <div className="text-[1.7rem] font-medium tabular-nums leading-none text-ink-900">
                    {row.successes}
                    <span className="text-[15px] text-ink-400">
                      /{row.runs}
                    </span>
                  </div>
                  <div className="mt-1.5 text-[12.5px] text-ink-500">
                    {row.denials > 0
                      ? `${row.denials} denial${row.denials > 1 ? "s" : ""} recorded`
                      : row.divergences > 0
                        ? `${row.divergences} divergences`
                        : "no divergence"}
                  </div>
                </div>
              </div>
            </Reveal>
          );
        })}
      </div>

      <div className="mt-10 grid grid-cols-1 gap-8 lg:grid-cols-[1.3fr_1fr]">
        <p className="max-w-prose text-[13.5px] leading-relaxed text-ink-500">
          C1 and C2 both pass every run and differ only in representation, so
          the {ratio}&times; gap is the price of an unbounded transcript. C2 and
          C3 spend identically, as they must: they differ by enforcement
          alone, and any gap in information cost would confound the contrast.
        </p>
        <div className="bg-marker/[0.09] p-5">
          <div className="text-[13px] font-medium text-ink-900">
            C3 splits 3/3 and 0/3.
          </div>
          <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-600">
            It matches C2 where agents own different files, and fails where
            they need the same one — enforcement prevents the clobber and
            blocks legitimate work at once. That is the trade-off, measured
            rather than assumed away.
          </p>
        </div>
      </div>
    </Section>
  );
}
