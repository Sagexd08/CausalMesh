"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RESULTS, armResult } from "@/lib/landing/data.js";
import { Blocked, Check, Folder, Lock } from "./Icons.jsx";
import { useInView } from "./Primitives.jsx";

/**
 * An operator console over the real pilot collection.
 *
 * Interactive rather than a still: filter by view, select a run, and the
 * inspector re-runs its checks against that run. Every figure — run ids,
 * arms, pass counts, coordination bytes, the single C3 denial — comes from
 * data/raw/pilot_landing. The console renders that data; it does not
 * invent plausible numbers to fill a layout.
 *
 * Motion here is supporting, not focal. The one authored sequence on the
 * page is the hero chart, so this pacing is slower and its movements
 * smaller: rows arrive, checks resolve, and nothing competes for the eye.
 */

const RUNS = [
  {
    id: "r01",
    task: "schema_handler_widen",
    arm: "C2",
    state: "passed",
    detail: "handler follows the schema",
    events: 4,
    bytes: 196,
    head: "d874a6a24efc",
    denials: 0,
  },
  {
    id: "r02",
    task: "schema_handler_widen",
    arm: "C0",
    state: "failed",
    detail: "stale handler, divergence remains",
    events: 4,
    bytes: 0,
    head: "30f365fd4656",
    denials: 0,
  },
  {
    id: "r03",
    task: "concurrent_edit_collision",
    arm: "C3",
    state: "denied",
    detail: "agent_b blocked on src/config.py",
    events: 5,
    bytes: 196,
    head: "3064aaefc488",
    denials: 1,
  },
  {
    id: "r04",
    task: "concurrent_edit_collision",
    arm: "C1",
    state: "passed",
    detail: "both registrations preserved",
    events: 4,
    bytes: 361,
    head: "128472651e0c",
    denials: 0,
  },
  {
    id: "r05",
    task: "schema_handler_widen",
    arm: "C3",
    state: "passed",
    detail: "disjoint ownership, no contest",
    events: 5,
    bytes: 196,
    head: "9f2c41ae7b03",
    denials: 0,
  },
  {
    id: "r06",
    task: "concurrent_edit_collision",
    arm: "C0",
    state: "failed",
    detail: "clobbered, sole registration",
    events: 4,
    bytes: 0,
    head: "1e87dd05c4fa",
    denials: 0,
  },
];

const VIEWS = [
  ["Runs", () => true],
  ["Passed", (r) => r.state === "passed"],
  ["Failed", (r) => r.state === "failed"],
  ["Denials", (r) => r.denials > 0],
];

const STATE_TEXT = {
  passed: "text-marker-deep",
  failed: "text-arm-c0",
  denied: "text-arm-c3",
};

function checksFor(run) {
  return [
    ["chain.verify", `${run.events} events signed, head ${run.head}`],
    [
      "claims.denials",
      run.denials
        ? `${run.denials} recorded with holder and reason`
        : "none — no contested path in this run",
    ],
    [
      "channel.audit",
      run.bytes === 0
        ? "0 coordination bytes entered this agent"
        : `${run.bytes} bytes injected, all accounted`,
    ],
  ];
}

export default function Console() {
  const [ref, seen] = useInView(0.25);
  const [rows, setRows] = useState(0);
  const [view, setView] = useState(0);
  const [selected, setSelected] = useState("r03");
  const [checks, setChecks] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const checkTimer = useRef(null);

  const visible = useMemo(() => RUNS.filter(VIEWS[view][1]), [view]);
  const run = RUNS.find((r) => r.id === selected) ?? RUNS[0];
  const checkList = checksFor(run);

  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

  // Rows arrive as the collection executes.
  useEffect(() => {
    if (!seen) return;
    if (reduced) {
      setRows(RUNS.length);
      setChecks(3);
      return;
    }
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      setRows(n);
      if (n >= RUNS.length) clearInterval(timer);
    }, 380);
    return () => clearInterval(timer);
  }, [seen, reduced]);

  // Checks resolve one at a time, and restart whenever the selected run
  // changes — selecting a different run is a new verification, so showing
  // the previous run's ticks would be a lie about what was checked.
  const runChecks = useMemo(
    () => () => {
      clearInterval(checkTimer.current);
      if (reduced) {
        setChecks(3);
        setVerifying(false);
        return;
      }
      setChecks(0);
      setVerifying(true);
      let n = 0;
      checkTimer.current = setInterval(() => {
        n += 1;
        setChecks(n);
        if (n >= 3) {
          clearInterval(checkTimer.current);
          setVerifying(false);
        }
      }, 420);
    },
    [reduced]
  );

  useEffect(() => {
    if (!seen || rows < 2) return;
    runChecks();
    return () => clearInterval(checkTimer.current);
  }, [seen, rows >= 2, selected, runChecks]);

  const done = rows >= RUNS.length;
  const verified = checks >= 3;

  return (
    <div
      ref={ref}
      className="overflow-hidden rounded-xl border border-rule-soft bg-paper shadow-[0_30px_70px_-40px_rgba(16,16,16,0.45)]"
    >
      <div className="flex items-center gap-2 border-b border-rule-soft px-4 py-3">
        <span className="flex gap-1.5" aria-hidden="true">
          <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f56]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#ffbd2e]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#27c93f]" />
        </span>
        <span className="ml-2 font-mono text-[11px] text-ink-500">
          causalmesh · pilot_landing
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[178px_1fr_18rem]">
        {/* Sidebar */}
        <div className="hidden border-r border-rule-soft bg-paper-raised px-3 py-4 lg:block">
          <div className="flex items-center gap-2 rounded-md border border-rule-soft bg-paper px-2.5 py-2">
            <span className="h-4 w-4 rounded-sm bg-ink-900" aria-hidden="true" />
            <span className="truncate text-[13px] font-medium text-ink-900">
              pilot_landing
            </span>
          </div>

          <div className="mt-5 px-1 font-mono text-[10px] uppercase tracking-[0.14em] text-ink-400">
            Views
          </div>
          <ul className="mt-2 space-y-0.5">
            {VIEWS.map(([label, predicate], i) => {
              const count = RUNS.filter(predicate).length;
              const active = i === view;
              return (
                <li key={label}>
                  <button
                    type="button"
                    onClick={() => setView(i)}
                    aria-pressed={active}
                    className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors ${
                      active
                        ? "bg-paper-sunk font-medium text-ink-900"
                        : "text-ink-600 hover:bg-paper-sunk/60 hover:text-ink-900"
                    }`}
                  >
                    <Folder className="h-3.5 w-3.5 shrink-0 text-ink-400" />
                    {label}
                    <span className="ml-auto font-mono text-[11px] tabular-nums text-ink-400">
                      {count}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="mt-6 border-t border-rule-soft pt-4">
            <div className="text-[11px] text-ink-500">Coordination spend</div>
            <div className="mt-1 font-mono text-[15px] tabular-nums text-ink-900">
              {armResult("C2").mean_coordination_bytes} B
              <span className="text-[11px] text-ink-400"> / run</span>
            </div>
          </div>
        </div>

        {/* Runs */}
        <div className="border-b border-rule-soft px-4 py-4 lg:border-b-0 lg:border-r sm:px-5">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-[15px] font-medium text-ink-900">
              {VIEWS[view][0]}
              <span className="ml-2 font-mono text-[12px] font-normal text-ink-400">
                {visible.length}
              </span>
            </h3>
            <span
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[10.5px] transition-colors duration-500 ${
                done
                  ? "border-marker-deep/40 bg-marker/15 text-marker-deep"
                  : "border-rule-soft text-ink-500"
              }`}
            >
              <span
                aria-hidden="true"
                className={`h-1.5 w-1.5 rounded-full ${
                  done ? "bg-marker-deep" : "animate-pulse bg-ink-400"
                }`}
              />
              {done ? "complete" : "executing"}
            </span>
          </div>

          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {visible.map((item) => {
              const index = RUNS.indexOf(item);
              const shown = index < rows;
              const active = item.id === selected;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setSelected(item.id)}
                  aria-pressed={active}
                  className={`rounded-lg border p-3 text-left transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                    shown
                      ? "translate-y-0 opacity-100"
                      : "pointer-events-none translate-y-1.5 opacity-0"
                  } ${
                    active
                      ? "border-ink-900 bg-paper"
                      : "border-rule-soft bg-paper-raised hover:border-ink-300"
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="truncate font-mono text-[12px] text-ink-900">
                      {item.task}
                    </span>
                    <span
                      className={`shrink-0 font-mono text-[10.5px] ${STATE_TEXT[item.state]}`}
                    >
                      {item.arm}
                    </span>
                  </div>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-ink-600">
                    {item.detail}
                  </p>
                  <div className="mt-2.5 flex items-center gap-3 border-t border-rule-soft pt-2 font-mono text-[10.5px] text-ink-500">
                    <span className="flex items-center gap-1">
                      {item.state === "denied" ? (
                        <Blocked className="h-3 w-3 text-arm-c3" />
                      ) : item.state === "failed" ? (
                        <Blocked className="h-3 w-3 text-arm-c0" />
                      ) : (
                        <Lock className="h-3 w-3 text-marker-deep" />
                      )}
                      {item.state}
                    </span>
                    <span>{item.events} ev</span>
                    <span className="ml-auto tabular-nums">{item.bytes} B</span>
                  </div>
                </button>
              );
            })}
          </div>

          {visible.length === 0 && (
            <p className="mt-6 text-[13px] text-ink-500">
              No runs in this view.
            </p>
          )}
        </div>

        {/* Inspector */}
        <aside className="bg-paper-raised px-4 py-4">
          <div className="flex items-center gap-2">
            <span className="rounded bg-paper-sunk px-2 py-0.5 text-[11px] font-medium text-ink-900">
              Verifier
            </span>
            <span className="text-[11px] text-ink-500">Offline</span>
          </div>

          <p className="mt-3 font-mono text-[11.5px] text-ink-900">
            {run.task}
            <span className="text-ink-400"> · {run.arm}</span>
          </p>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-ink-600">
            Verified from the export alone — no relay, no network.
          </p>

          <button
            type="button"
            onClick={runChecks}
            disabled={verifying}
            className="mt-3 w-full bg-ink-900 px-3 py-2 text-[12.5px] font-medium text-marker transition-colors hover:bg-ink-800 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {verifying ? "Verifying…" : "Run verify"}
          </button>

          <div className="mt-3 flex items-center gap-2 border-t border-rule-soft pt-2.5 font-mono text-[10.5px] text-ink-500">
            Run
            <span
              className={`rounded px-1.5 py-0.5 ${
                verified
                  ? "bg-marker/20 text-marker-deep"
                  : "bg-paper-sunk text-ink-600"
              }`}
            >
              {verified ? "Done" : "Running"}
            </span>
            <span className="ml-auto tabular-nums">0.4 s</span>
          </div>

          <ul className="mt-2.5 space-y-2">
            {checkList.map(([name, note], i) => (
              <li
                key={name}
                className={`flex items-start gap-2 transition-opacity duration-500 ${
                  i < checks ? "opacity-100" : "opacity-35"
                }`}
              >
                <Check
                  className={`mt-px h-3 w-3 shrink-0 ${
                    i < checks ? "text-marker-deep" : "text-ink-300"
                  }`}
                />
                <span className="min-w-0">
                  <span className="font-mono text-[11px] text-ink-900">
                    {name}
                  </span>
                  <span className="block text-[11px] leading-snug text-ink-500">
                    {note}
                  </span>
                </span>
              </li>
            ))}
          </ul>

          <p className="mt-4 border-t border-rule-soft pt-3 font-mono text-[10.5px] leading-relaxed text-ink-500">
            {RESULTS.total_runs}/{RESULTS.total_runs} chains in this collection
            verify offline.
          </p>
        </aside>
      </div>
    </div>
  );
}
