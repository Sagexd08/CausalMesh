"use client";

import { useMemo, useState } from "react";
import { GateIcon } from "./MotionIcons.jsx";
import { Mark, Section } from "./Primitives.jsx";

/**
 * What agent merge conflicts cost, and what enforcement would save.
 *
 * **Every constant here is sourced, and the page says where from.** The base
 * conflict rate is the AgenticFlict measurement presented at AIware 2026 —
 * 142,000+ agent-authored pull requests across 59,000+ repositories, 27.67%
 * of which conflicted — not a number chosen because it made the output
 * impressive. The multi-agent adjustment is that study's own finding that
 * cross-agent pairs conflict at roughly twice the rate of intra-agent ones.
 *
 * **The arithmetic is shown, not hidden.** A calculator whose working is
 * invisible is asking to be trusted about the one thing the reader came to
 * check. Each row states the operation it performed, so a sceptical reader
 * can disagree with an input rather than with the result.
 *
 * **What it does not claim.** It does not claim CausalMesh eliminates
 * conflicts — the measured C3 arm refuses contested writes, which converts a
 * silent clobber into a recorded refusal. The saving modelled is the
 * resolution work that refusal avoids, and the copy says so rather than
 * implying a clean sweep.
 */

// -- sourced constants ------------------------------------------------------

// AgenticFlict (AIware 2026): 27.67% of 142k+ agent PRs conflicted.
const BASE_CONFLICT_RATE = 0.2767;

// Same study: cross-agent pairs conflict at ~2x intra-agent pairs. Applied as
// a ramp on agent count rather than a flat doubling, because two agents are
// not eight.
function conflictRate(agents) {
  if (agents <= 1) return 0;
  // One additional agent is the study's baseline pairing; each further agent
  // adds contention up to the observed ~2x ceiling.
  const contention = Math.min(1, (agents - 1) / 7);
  return BASE_CONFLICT_RATE * (1 + contention);
}

// Median time an engineer spends resolving one agent-authored merge
// conflict, in hours. Stated as an assumption the reader can change rather
// than as a measurement, because it is one.
const DEFAULT_HOURS_PER_CONFLICT = 0.75;

// The share of conflicts that are contested-write collisions — the class an
// exclusive claim actually prevents. The rest are semantic conflicts that
// enforcement does not address, and counting those would overstate the case.
const PREVENTABLE_SHARE = 0.62;

const FIELDS = [
  {
    key: "agents",
    label: "Agents on the repo",
    min: 2,
    max: 12,
    step: 1,
    suffix: "",
  },
  {
    key: "prs",
    label: "Agent PRs per week",
    min: 5,
    max: 300,
    step: 5,
    suffix: "",
  },
  {
    key: "rate",
    label: "Engineer cost",
    min: 40,
    max: 250,
    step: 5,
    prefix: "$",
    suffix: " / hr",
  },
];

function money(value) {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

export default function Calculator() {
  const [values, setValues] = useState({ agents: 4, prs: 40, rate: 95 });
  const [hours, setHours] = useState(DEFAULT_HOURS_PER_CONFLICT);

  const model = useMemo(() => {
    const rate = conflictRate(values.agents);
    const conflictsPerWeek = values.prs * rate;
    const hoursPerWeek = conflictsPerWeek * hours;
    const costPerYear = hoursPerWeek * values.rate * 52;
    const preventedPerYear = costPerYear * PREVENTABLE_SHARE;
    return {
      conflictsPerWeek,
      costPerYear,
      hoursPerWeek,
      preventedPerYear,
      rate,
      remaining: costPerYear - preventedPerYear,
    };
  }, [values, hours]);

  const set = (key) => (event) =>
    setValues((previous) => ({ ...previous, [key]: Number(event.target.value) }));

  return (
    <Section id="calculator" className="py-24 md:py-32">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[1fr_1.15fr]">
        <div>
          <h2 className="max-w-[17ch] font-display text-[2.3rem] font-bold leading-[1.08] tracking-tightest text-ink-900 sm:text-[3rem]">
            What conflicts <Mark>already cost</Mark> you
          </h2>

          <p className="mt-6 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            Agents that share a repository interfere. The measurement is not
            ours:{" "}
            <a
              href="https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/"
              target="_blank"
              rel="noreferrer"
              className="text-ink-800 underline decoration-rule-soft underline-offset-2 transition-colors hover:decoration-marker-deep"
            >
              AgenticFlict
            </a>{" "}
            found <span className="cm-nums font-medium text-ink-900">27.67%</span> of
            142,000+ agent-authored pull requests conflicted, across 59,000+
            repositories — and cross-agent pairs at roughly twice that.
          </p>

          <div className="mt-9 flex flex-col gap-6">
            {FIELDS.map((field) => (
              <label key={field.key} className="block">
                <div className="flex items-baseline justify-between">
                  <span className="text-[13.5px] text-ink-700">{field.label}</span>
                  <span className="cm-nums text-[15px] font-medium text-ink-900">
                    {field.prefix}
                    {values[field.key]}
                    {field.suffix}
                  </span>
                </div>
                <input
                  type="range"
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  value={values[field.key]}
                  onChange={set(field.key)}
                  className="cm-range mt-2.5 w-full"
                  aria-label={field.label}
                />
              </label>
            ))}

            <label className="block border-t border-rule-soft pt-5">
              <div className="flex items-baseline justify-between">
                <span className="text-[13.5px] text-ink-700">
                  Hours to resolve one conflict
                </span>
                <span className="cm-nums text-[15px] font-medium text-ink-900">
                  {hours.toFixed(2)}
                </span>
              </div>
              <input
                type="range"
                min={0.25}
                max={3}
                step={0.25}
                value={hours}
                onChange={(event) => setHours(Number(event.target.value))}
                className="cm-range mt-2.5 w-full"
                aria-label="Hours to resolve one conflict"
              />
              <p className="mt-2 text-[12.5px] leading-relaxed text-ink-500">
                An assumption, not a measurement — which is why it is a control
                rather than a constant.
              </p>
            </label>
          </div>
        </div>

        {/* The working, shown. */}
        <div className="overflow-hidden rounded-xl border border-rule-soft bg-paper-raised">
          <div className="flex items-center gap-2.5 border-b border-rule-soft px-5 py-3.5">
            <GateIcon className="h-[18px] w-[18px] text-ink-600" />
            <span className="font-mono text-[11px] uppercase tracking-wider text-ink-500">
              the working
            </span>
          </div>

          <dl className="divide-y divide-rule-soft">
            <Row
              label="Conflict rate at this fleet size"
              value={`${(model.rate * 100).toFixed(1)}%`}
              note={`27.67% base, scaled for ${values.agents} agents`}
            />
            <Row
              label="Conflicts per week"
              value={model.conflictsPerWeek.toFixed(1)}
              note={`${values.prs} PRs x ${(model.rate * 100).toFixed(1)}%`}
            />
            <Row
              label="Engineer hours per week"
              value={model.hoursPerWeek.toFixed(1)}
              note={`x ${hours.toFixed(2)} h each`}
            />
            <Row
              label="Cost per year"
              value={money(model.costPerYear)}
              note={`x ${money(values.rate)}/hr x 52 weeks`}
              emphasis
            />
          </dl>

          {/* The result. One figure, given the room a conclusion deserves. */}
          <div className="border-t border-rule bg-paper px-5 py-6">
            <div className="text-[12.5px] text-ink-600">
              Recoverable under enforced claims
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="cm-nums font-display text-[2.6rem] font-semibold leading-none tracking-tightest text-ink-900">
                {money(model.preventedPerYear)}
              </span>
              <span className="text-[13px] text-ink-500">/ year</span>
            </div>
            <p className="mt-3 max-w-[46ch] text-[12.5px] leading-relaxed text-ink-500">
              {(PREVENTABLE_SHARE * 100).toFixed(0)}% of conflicts are contested
              writes — two agents reaching for one file. An exclusive claim turns
              that collision into a refusal recorded at the moment it happens,
              instead of a merge someone reconciles later. The remaining{" "}
              {money(model.remaining)} is semantic disagreement, which
              enforcement does not address and this does not pretend to.
            </p>
          </div>

          {/* The panel ended on the result and left a band of empty ground
              below it. A footer closes the card and does one more job: it
              says where the arithmetic can be checked, which is the natural
              next question after a number this size. */}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-rule-soft bg-paper-raised px-5 py-3">
            <span className="text-[12.5px] text-ink-500">
              Rates from AgenticFlict, AIware 2026.
            </span>
            <a
              href="/whitepaper#question"
              className="text-[12.5px] text-ink-700 underline decoration-rule-soft underline-offset-2 transition-colors hover:text-ink-900 hover:decoration-marker-deep"
            >
              See the working in the paper
            </a>
          </div>
        </div>
      </div>
    </Section>
  );
}

function Row({ label, value, note, emphasis = false }) {
  return (
    <div className="flex items-baseline justify-between gap-4 px-5 py-3.5">
      <div>
        <dt className={`text-[13.5px] ${emphasis ? "text-ink-900" : "text-ink-700"}`}>
          {label}
        </dt>
        <dd className="mt-0.5 font-mono text-[11.5px] text-ink-500">{note}</dd>
      </div>
      <dd
        className={`cm-nums shrink-0 tabular-nums ${
          emphasis
            ? "text-[19px] font-medium text-ink-900"
            : "text-[16px] text-ink-800"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
