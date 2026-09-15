"use client";

import { useState } from "react";
import agentMarks from "@/lib/landing/agent-marks.json";
import { Check } from "./Icons.jsx";
import { Mark, Section } from "./Primitives.jsx";

/**
 * Which agents the substrate can drive, and what wiring one up involves.
 *
 * Selecting an agent rewrites the steps beside it. That interaction is the
 * point: the claim is that the adapter layer is provider-neutral, and a
 * panel where only the name changes demonstrates it more honestly than a
 * paragraph saying so.
 *
 * The honesty constraint: the adapters are built and tested over real HTTP,
 * but **no hosted model has been run through them**. The panel says which
 * state each integration is actually in rather than showing every one as
 * "Ready", which is what a marketing page would do.
 */

const STATUS = {
  tested: ["Adapter tested", "text-marker-deep bg-marker/15 border-marker-deep/40"],
  untested: ["Not yet run", "text-ink-600 bg-paper-sunk border-rule-soft"],
};

const AGENTS = agentMarks.map((agent, i) => ({
  ...agent,
  // The three adapters that exist are the ones exercised by the test suite.
  status: i < 3 ? "tested" : "untested",
}));

function AgentMark({ agent, alt = "", className = "" }) {
  return (
    <span
      className={`flex h-7 w-7 shrink-0 items-center justify-center border border-rule-soft bg-paper ${className}`}
    >
      <img
        src={agent.src}
        alt={alt}
        className="h-5 w-5 object-contain"
      />
    </span>
  );
}

function stepsFor(name) {
  return [
    [
      "Point it at the relay",
      `causalmesh serve --agent ${name.toLowerCase().replace(/\s+/g, "-")}`,
      "The substrate speaks the chat-completions wire protocol, so any OpenAI-compatible client connects.",
    ],
    [
      "Declare what it owns",
      "roles:\n  - agent_id: agent_a\n    owns: [src/schema.py]",
      "Ownership drives the claim registry and the relevance scorer. Nothing is inferred from behaviour.",
    ],
    [
      "Run under an arm",
      "causalmesh run --arm C3 --task schema_handler_widen",
      "The arm installs a channel and a gate. Nothing reads the arm name at runtime.",
    ],
  ];
}

export default function Agents() {
  const [selected, setSelected] = useState(0);
  const agent = AGENTS[selected];
  const steps = stepsFor(agent.name);

  return (
    <Section id="agents" className="py-24 md:py-32">
      <div className="grid grid-cols-1 gap-x-16 gap-y-12 lg:grid-cols-[1fr_1.1fr]">
        <div>
          <h2 className="max-w-[16ch] font-display text-[2.3rem] font-bold leading-[1.08] tracking-tightest text-ink-900 sm:text-[3rem]">
            Keep your agent. Change the <Mark>substrate</Mark>
          </h2>
          <p className="mt-6 max-w-prose text-[15.5px] leading-relaxed text-ink-600">
            The adapter layer is provider-neutral and speaks the
            chat-completions wire protocol rather than a vendor SDK. Pick a
            client to see what wiring it up involves.
          </p>

          <div className="mt-9 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-2 xl:grid-cols-3">
            {AGENTS.map((item, i) => {
              const active = i === selected;
              return (
                <button
                  key={item.name}
                  type="button"
                  onClick={() => setSelected(i)}
                  aria-pressed={active}
                  className={`flex items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-all duration-200 ${
                    active
                      ? "border-ink-900 bg-paper shadow-[0_6px_18px_-12px_rgba(16,16,16,0.5)]"
                      : "border-rule-soft bg-paper-raised hover:border-ink-300"
                  }`}
                >
                  <AgentMark agent={item} />
                  <span
                    className={`truncate text-[13px] ${
                      active ? "font-medium text-ink-900" : "text-ink-700"
                    }`}
                  >
                    {item.name}
                  </span>
                </button>
              );
            })}
          </div>

          <p className="mt-5 text-[13px] leading-relaxed text-ink-500">
            Three adapters are built and tested against a real HTTP endpoint.
            No hosted model has been run through them yet — that needs an API
            key and a budget, and the page says so rather than showing eight
            green ticks.
          </p>
        </div>

        {/* Setup panel */}
        <div className="overflow-hidden rounded-xl border border-rule-soft bg-paper-raised">
          <div className="flex items-center gap-3 border-b border-rule-soft px-5 py-3.5">
            <AgentMark agent={agent} alt={`${agent.name} mark`} />
            <span className="text-[15px] font-medium text-ink-900">
              {agent.name}
            </span>
            <span
              className={`ml-auto rounded-full border px-2.5 py-0.5 font-mono text-[10.5px] ${
                STATUS[agent.status][1]
              }`}
            >
              {STATUS[agent.status][0]}
            </span>
          </div>

          <ol className="divide-y divide-rule-soft">
            {steps.map(([title, code, note], i) => (
              <li key={title} className="px-5 py-4">
                <div className="flex items-baseline gap-3">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-rule-soft font-mono text-[10.5px] tabular-nums text-ink-600">
                    {i + 1}
                  </span>
                  <h3 className="text-[14.5px] font-medium text-ink-900">
                    {title}
                  </h3>
                </div>
                <pre className="mt-2.5 overflow-x-auto rounded-md border border-rule-soft bg-paper px-3 py-2.5 font-mono text-[11.5px] leading-relaxed text-ink-800">
                  <code>{code}</code>
                </pre>
                <p className="mt-2 text-[12.5px] leading-relaxed text-ink-500">
                  {note}
                </p>
              </li>
            ))}
          </ol>

          <div className="flex items-center gap-2 border-t border-rule-soft bg-paper px-5 py-3">
            <Check className="h-3.5 w-3.5 text-marker-deep" />
            <span className="text-[12.5px] text-ink-600">
              Every call passes the gate and enters the signed chain,
              whichever client made it.
            </span>
          </div>
        </div>
      </div>
    </Section>
  );
}
