import { RESULTS, armResult } from "@/lib/landing/data.js";
import Chart from "./Chart.jsx";
import { Check, GitHubMark } from "./Icons.jsx";
import { ButtonGhost, ButtonPrimary, Mark, Section } from "./Primitives.jsx";

export default function Hero() {
  const c1 = armResult("C1");
  const c2 = armResult("C2");
  const saving = Math.round(
    ((c1.mean_coordination_bytes - c2.mean_coordination_bytes) /
      c1.mean_coordination_bytes) *
      100
  );

  const FIGURES = [
    [
      "Coordination cost",
      c2.mean_coordination_bytes,
      "B / run",
      `${saving}% under transcript`,
      false,
    ],
    ["Isolated arm", "0", "bytes in", "proven, not asserted", false],
    [
      "Chains verified",
      RESULTS.total_runs,
      `/ ${RESULTS.total_runs}`,
      "offline, no relay",
      true,
    ],
    [
      "Denials recorded",
      armResult("C3").denials,
      "with holder",
      "actor · path · why",
      false,
    ],
  ];

  return (
    <Section className="pt-16 pb-20 md:pt-24">
      <div className="grid grid-cols-1 items-start gap-x-16 gap-y-14 lg:grid-cols-[1fr_1.15fr]">
        <div>
          {/* Two facts, and the licence is the first of them. Someone
              deciding whether to read further asks "can I use this" before
              they ask "does it work", and MIT answers that in three
              characters. It links to the licence rather than decorating,
              because a badge that goes nowhere is an image of a badge. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13px]">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-ink-900 px-2.5 py-1 text-ink-900">
              <GitHubMark className="h-3.5 w-3.5" />
              <span className="font-medium">Releasing soon</span>
              <span className="text-ink-500">MIT</span>
            </span>

            <span className="flex items-center gap-2 text-ink-600">
              <span className="inline-flex h-5 w-5 items-center justify-center bg-ink-900 text-marker">
                <Check className="h-3 w-3" />
              </span>
              982 tests &middot; 24 runs &middot; every chain verified
            </span>
          </div>

          <h1 className="mt-7 font-display text-[2.7rem] font-extrabold leading-[1.05] tracking-tightest text-ink-900 sm:text-[3.4rem] lg:text-[3.9rem]">
            Coordination
            <br />
            you can <Mark>prove</Mark>
          </h1>

          <p className="mt-7 max-w-[46ch] text-[16px] leading-relaxed text-ink-600">
            Gate every action. Sign every action. Record every refusal with its
            reason. Every other layer tells agents what to do — this is the one
            that proves what they did, and refuses what they shouldn&rsquo;t.
          </p>

          <div className="mt-9 flex flex-wrap items-center gap-4">
            <ButtonPrimary href="#results">See the results</ButtonPrimary>
            <ButtonGhost href="#architecture">How it works</ButtonGhost>
          </div>
        </div>

        <Chart />
      </div>

      <div className="mt-16 grid grid-cols-2 gap-x-10 gap-y-8 border-t border-rule-soft pt-8 md:grid-cols-4">
        {FIGURES.map(([label, value, unit, caption, accent]) => (
          <div key={label}>
            <div className="text-[12.5px] text-ink-600">{label}</div>
            <div className="mt-1.5 flex items-baseline gap-1.5">
              <span
                className={`text-[2rem] font-medium tabular-nums ${
                  accent ? "text-marker-deep" : "text-ink-900"
                }`}
              >
                {value}
              </span>
              <span className="text-[13px] text-ink-500">{unit}</span>
            </div>
            <div className="mt-1 text-[12.5px] text-ink-500">{caption}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}
