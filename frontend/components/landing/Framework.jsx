"use client";

import { useState } from "react";
import { Check } from "./Icons.jsx";
import { Mark, Section } from "./Primitives.jsx";

/**
 * The framework thesis: one substrate, three kinds of agent.
 *
 * This section exists because the project's scope changed. The rest of the
 * page describes a coding-agent experiment, which is what was measured; this
 * says what the measured thing is *for*. Keeping it as its own section rather
 * than rewriting the hero means the evidence-backed claims and the
 * forward-looking ones stay visually separable, which is the same discipline
 * the Agents panel already applies to tested vs untested adapters.
 *
 * **The load-bearing idea.** A refused write and a refused payment are the
 * same primitive: a gate consults declared authority, denies, and records the
 * denial. That is why one substrate can cover agents that write code, agents
 * that spend money, and agents that run unattended — they differ in payload
 * and in nothing the substrate cares about.
 *
 * **Honesty.** Only the `write` lane is built and measured today. The panel
 * labels each lane with its real state rather than showing three green ticks,
 * and the shipped/planned split is stated in the footer rather than implied.
 */

const LANES = [
  {
    id: "write",
    kind: "Coding agents",
    tagline: "Claude Code, Codex, Cursor, Aider…",
    status: "measured",
    action: "WRITE",
    resource: "src/config.py",
    verdict: "REFUSED",
    reason: "held by agent_a",
    note: "Two agents reach for one file. The second is refused, and the refusal is signed into the chain as evidence rather than logged and lost.",
  },
  {
    id: "spend",
    kind: "Payment agents",
    tagline: "x402, MPP — agents that buy",
    status: "planned",
    action: "PAY",
    resource: "2.40 USDC → premium.unknown.io",
    verdict: "REFUSED",
    reason: "host not allowed; over per-call ceiling",
    note: "An x402 flow answers HTTP 402 with a price. The gate sits at 'agent pays'. A clobbered file is recoverable; a spent dollar is not.",
  },
  {
    id: "act",
    kind: "Autonomous agents",
    tagline: "long-running, scheduled, delegating",
    status: "planned",
    action: "SPAWN",
    resource: "subagent · 200k token budget",
    verdict: "REFUSED",
    reason: "budget exhausted at 200k",
    note: "Open-ended agent loops are the biggest cost risk in production. A budget that refuses is a budget; one that reports is an invoice.",
  },
];

const STATUS = {
  measured: ["Built · measured", "text-marker-deep bg-marker/15 border-marker-deep/40"],
  planned: ["Planned", "text-ink-600 bg-paper-sunk border-rule-soft"],
};

const PLANES = [
  ["Contract", "causalmesh.yaml", "Who each agent is, what it owns, what it may spend. Declared and diffable — never inferred from behaviour."],
  ["Enforcement", "the gate", "Consults the contract, allows or refuses. The refusal is the product, not the error path."],
  ["Evidence", "the signed chain", "Ed25519, hash-linked, verifiable offline with the relay stopped."],
  ["Measurement", "the four arms", "Whether a convention actually paid for itself. Nothing else in this space can answer that."],
];

function Lane({ lane, active, onSelect }) {
  const [label, tone] = STATUS[lane.status];
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={`w-full rounded-lg border px-4 py-3.5 text-left transition-all duration-200 ${
        active
          ? "border-ink-900 bg-paper shadow-[0_6px_18px_-12px_rgba(16,16,16,0.5)]"
          : "border-rule-soft bg-paper-raised hover:border-ink-300"
      }`}
    >
      <div className="flex items-center gap-2.5">
        <span
          className={`text-[14.5px] ${
            active ? "font-medium text-ink-900" : "text-ink-700"
          }`}
        >
          {lane.kind}
        </span>
        <span
          className={`ml-auto shrink-0 rounded-full border px-2 py-0.5 font-mono text-[10px] ${tone}`}
        >
          {label}
        </span>
      </div>
      <div className="mt-1 text-[12.5px] text-ink-500">{lane.tagline}</div>
    </button>
  );
}

export default function Framework() {
  const [selected, setSelected] = useState(0);
  const lane = LANES[selected];

  return (
    <Section id="framework" className="py-24 md:py-32">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[1fr_1.1fr]">
        <div>
          <h2 className="max-w-[18ch] font-display text-[2.3rem] font-bold leading-[1.08] tracking-tightest text-ink-900 sm:text-[3rem]">
            A framework for agents that <Mark>answers for them</Mark>
          </h2>

          <p className="mt-6 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            Agents write code, spend money, and run unattended. Three questions
            follow all of them: what did it do, was it allowed to, and can you
            prove it afterwards. Orchestration libraries answer the first.
            CausalMesh is built for the other two.
          </p>

          <p className="mt-4 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            One primitive covers all three: a refused write and a refused
            payment are the same event. A gate consults declared authority,
            denies, and records the denial. They differ in payload and in
            nothing the substrate cares about.
          </p>

          <div className="mt-9 flex flex-col gap-2">
            {LANES.map((item, i) => (
              <Lane
                key={item.id}
                lane={item}
                active={i === selected}
                onSelect={() => setSelected(i)}
              />
            ))}
          </div>

          <p className="mt-5 text-[13px] leading-relaxed text-ink-500">
            The coding lane is built and measured — every figure on this page
            comes from it. The other two are planned and labelled as such. See{" "}
            <a
              href="/docs"
              className="text-ink-700 underline decoration-rule-soft underline-offset-2 hover:text-ink-900"
            >
              the docs
            </a>{" "}
            for what exists today.
          </p>
        </div>

        <div className="flex flex-col gap-5">
          {/* What the gate does, in the selected lane's own terms. */}
          <div className="overflow-hidden rounded-xl border border-rule-soft bg-paper-raised">
            <div className="flex items-center gap-3 border-b border-rule-soft px-5 py-3.5">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-500">
                the gate
              </span>
              <span className="ml-auto text-[12.5px] text-ink-600">
                {lane.kind}
              </span>
            </div>

            <div className="px-5 py-5">
              <pre className="overflow-x-auto rounded-md border border-rule-soft bg-paper px-3.5 py-3 font-mono text-[11.5px] leading-relaxed text-ink-800">
                <code>
                  {lane.action} {lane.resource}
                </code>
              </pre>

              <div className="mt-3.5 flex items-baseline gap-2.5">
                <span className="rounded border border-marker-deep/40 bg-marker/15 px-2 py-0.5 font-mono text-[10.5px] text-marker-deep">
                  {lane.verdict}
                </span>
                <span className="font-mono text-[12px] text-ink-600">
                  {lane.reason}
                </span>
              </div>

              <p className="mt-4 text-[13px] leading-relaxed text-ink-500">
                {lane.note}
              </p>
            </div>

            <div className="flex items-center gap-2 border-t border-rule-soft bg-paper px-5 py-3">
              <Check className="h-3.5 w-3.5 text-marker-deep" />
              <span className="text-[12.5px] text-ink-600">
                Every refusal is signed and enters the chain with its reason.
              </span>
            </div>
          </div>

          {/* The four planes, stated once. */}
          <div className="overflow-hidden rounded-xl border border-rule-soft bg-paper-raised">
            <div className="border-b border-rule-soft px-5 py-3.5">
              <span className="font-mono text-[11px] uppercase tracking-wider text-ink-500">
                four planes
              </span>
            </div>
            <ol className="divide-y divide-rule-soft">
              {PLANES.map(([name, what, why], i) => (
                <li key={name} className="flex gap-3.5 px-5 py-3.5">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-rule-soft font-mono text-[10.5px] tabular-nums text-ink-600">
                    {i + 1}
                  </span>
                  <div>
                    <div className="flex items-baseline gap-2">
                      <span className="text-[14px] font-medium text-ink-900">
                        {name}
                      </span>
                      <span className="font-mono text-[11.5px] text-ink-500">
                        {what}
                      </span>
                    </div>
                    <p className="mt-1 text-[12.5px] leading-relaxed text-ink-500">
                      {why}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </Section>
  );
}
