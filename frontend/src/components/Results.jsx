import { ARMS, RESULTS, armResult } from "../data.js";
import { Eyebrow, Reveal, Section, Stat } from "./Primitives.jsx";

const ARM_COLOR = {
  C0: "bg-arm-c0",
  C1: "bg-arm-c1",
  C2: "bg-arm-c2",
  C3: "bg-arm-c3",
};
const ARM_TEXT = {
  C0: "text-arm-c0",
  C1: "text-arm-c1",
  C2: "text-arm-c2",
  C3: "text-arm-c3",
};

/** Horizontal bar, width proportional to the success rate. */
function RateBar({ arm, rate, runs, successes }) {
  const pct = Math.round(rate * 100);
  return (
    <div
      className="flex items-center gap-3"
      role="img"
      aria-label={`${arm}: ${successes} of ${runs} runs succeeded, ${pct} percent`}
    >
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div
          className={`h-full rounded-full ${ARM_COLOR[arm]} transition-[width] duration-1000 ease-out`}
          style={{ width: `${Math.max(pct, 1.5)}%` }}
        />
      </div>
      <span className="w-14 shrink-0 text-right font-mono text-[12px] tabular-nums text-chalk-400">
        {successes}/{runs}
      </span>
    </div>
  );
}

export default function Results() {
  const maxBytes = Math.max(
    ...RESULTS.arms.map((a) => a.mean_coordination_bytes)
  );

  return (
    <Section id="results" className="py-24 md:py-32">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-12 gap-y-10 items-end">
        <div className="lg:col-span-7">
          <Eyebrow>Measured, not asserted</Eyebrow>
          <h2 className="mt-6 text-3xl md:text-[2.6rem] leading-[1.1] font-semibold tracking-tightest text-chalk-100">
            {RESULTS.total_runs} runs. Two tasks.
            <br />
            Every chain verified.
          </h2>
        </div>
        <div className="lg:col-span-5">
          <p className="max-w-prose text-[15px] leading-relaxed text-chalk-500">
            A real pilot collection executed on one machine in 150&nbsp;seconds.
            Every figure on this page comes from{" "}
            <span className="font-mono text-[13px] text-chalk-300">
              data/raw/
            </span>
            . None of it is illustrative.
          </p>
        </div>
      </div>

      <div className="mt-14 overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-left">
          <caption className="sr-only">
            Success rate, coordination cost, denials and divergences by
            experimental arm
          </caption>
          <thead>
            <tr className="border-b border-white/[0.09]">
              {[
                "Arm",
                "Information",
                "Enforcement",
                "Success",
                "Coord. bytes",
                "Denials",
                "Divergences",
              ].map((h, i) => (
                <th
                  key={h}
                  scope="col"
                  className={`pb-3 font-mono text-[11px] font-normal uppercase tracking-[0.14em] text-chalk-600 ${
                    i >= 4 ? "text-right" : ""
                  }`}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]">
            {ARMS.map((arm) => {
              const r = armResult(arm.id);
              return (
                <tr key={arm.id}>
                  <th scope="row" className="py-5 pr-6 align-top font-normal">
                    <div className="flex items-baseline gap-2.5">
                      <span
                        className={`font-mono text-[15px] font-medium ${ARM_TEXT[arm.id]}`}
                      >
                        {arm.id}
                      </span>
                      <span className="text-[15px] text-chalk-200">
                        {arm.name}
                      </span>
                    </div>
                  </th>
                  <td className="py-5 pr-6 align-top text-[14px] text-chalk-500">
                    {arm.information}
                  </td>
                  <td className="py-5 pr-6 align-top text-[14px] text-chalk-500">
                    {arm.enforcement}
                  </td>
                  <td className="w-[26%] py-5 pl-6 align-top">
                    <RateBar
                      arm={arm.id}
                      rate={r.success_rate}
                      runs={r.runs}
                      successes={r.successes}
                    />
                  </td>
                  <td className="py-5 pl-6 text-right align-top font-mono text-[14px] tabular-nums text-chalk-200">
                    {r.mean_coordination_bytes}
                  </td>
                  <td
                    className={`py-5 pl-6 text-right align-top font-mono text-[14px] tabular-nums ${
                      r.denials ? "text-arm-c3" : "text-chalk-600"
                    }`}
                  >
                    {r.denials}
                  </td>
                  <td
                    className={`py-5 pl-6 text-right align-top font-mono text-[14px] tabular-nums ${
                      r.divergences ? "text-arm-c0" : "text-chalk-600"
                    }`}
                  >
                    {r.divergences}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-20 grid grid-cols-1 lg:grid-cols-12 gap-x-12 gap-y-12">
        <div className="lg:col-span-5">
          <Eyebrow tone="muted">Coordination cost</Eyebrow>
          <h3 className="mt-5 text-2xl leading-tight font-medium text-chalk-100">
            The transcript costs 84% more
            <br />
            for the same outcome.
          </h3>
          <p className="mt-5 max-w-prose text-[15px] leading-relaxed text-chalk-500">
            C1 and C2 both succeed on every run. They differ only in how the
            same information is represented — and that difference is the whole
            operating cost of a long-running fleet.
          </p>
          <p className="mt-4 max-w-prose text-[15px] leading-relaxed text-chalk-500">
            C2 and C3 spend{" "}
            <span className="text-chalk-200">identically</span>, as they must:
            they differ by enforcement alone, so any gap in information cost
            would confound the contrast.
          </p>
        </div>

        <div className="lg:col-span-7 flex items-end gap-5 sm:gap-8 pb-2">
          {RESULTS.arms.map((r) => {
            const height = maxBytes
              ? Math.max((r.mean_coordination_bytes / maxBytes) * 100, 1)
              : 1;
            return (
              <div key={r.arm} className="flex flex-1 flex-col items-center">
                <span className="mb-2 font-mono text-[12px] tabular-nums text-chalk-400">
                  {r.mean_coordination_bytes}
                </span>
                <div
                  className={`w-full rounded-t-sm ${ARM_COLOR[r.arm]} opacity-90`}
                  style={{ height: `${height * 1.7}px` }}
                  role="img"
                  aria-label={`${r.arm}: ${r.mean_coordination_bytes} mean coordination bytes`}
                />
                <span
                  className={`mt-3 font-mono text-[12px] ${ARM_TEXT[r.arm]}`}
                >
                  {r.arm}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <Reveal>
        <div className="mt-20 rule rounded-lg border bg-ink-900/50 p-7 md:p-9">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-x-10 gap-y-6">
            <div className="lg:col-span-4">
              <Eyebrow tone="muted">The finding</Eyebrow>
              <h3 className="mt-4 text-xl leading-snug font-medium text-chalk-100">
                Enforcement is not
                <br />
                strictly an improvement.
              </h3>
            </div>
            <div className="lg:col-span-8">
              <p className="max-w-prose text-[15px] leading-relaxed text-chalk-400">
                C3 splits: <span className="font-mono text-chalk-200">3/3</span>{" "}
                where the agents own different files, and{" "}
                <span className="font-mono text-chalk-200">0/3</span> where they
                genuinely need the same one.
              </p>
              <p className="mt-4 max-w-prose text-[15px] leading-relaxed text-chalk-500">
                On the contested task, exclusive locking prevents the clobber{" "}
                <em className="not-italic text-chalk-300">and</em> blocks
                legitimate work — the file needs two writers. That is a result
                about enforcement, not a defect in the gate, and it is exactly
                the trade-off a deployment decision turns on.
              </p>
            </div>
          </div>
        </div>
      </Reveal>

      <div className="mt-16 grid grid-cols-2 gap-8 border-t border-white/[0.07] pt-10 md:grid-cols-4">
        <Stat value="24" label="runs executed" />
        <Stat
          value="24"
          unit="/24"
          label="chains verified offline"
          tone="signal"
        />
        <Stat value="0" label="coordination bytes in C0" />
        <Stat value="797" label="tests passing" />
      </div>
    </Section>
  );
}
