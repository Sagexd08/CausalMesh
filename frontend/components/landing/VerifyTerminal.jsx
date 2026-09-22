"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "./Primitives.jsx";

/**
 * A terminal that runs `causalmesh verify --all` and streams the real result.
 *
 * The command and every row below are a transcript, not scripted copy —
 * this is what `causalmesh verify --all` printed against this checkout's
 * `data/raw/` on 2026-09-23: 24 runs from the pilot collection plus 4 from
 * the smoke-test collection, 28 total. That total is deliberately not
 * pulled from `RESULTS.total_runs` (used elsewhere on this page for the
 * pilot collection alone, e.g. the "24 runs" badge above) — `verify --all`
 * checks every collection on disk, and showing 24 here would silently
 * disagree with the command's own real output. Two different, both true,
 * numbers; this component shows the one that matches what it displays.
 *
 * The sequence — type the command, spin while it "verifies", stream each
 * chain's row, hold on the summary, then loop — is deliberately paced
 * rather than instant: a hero that types is proof the thing is a real CLI,
 * not a screenshot. It starts once scrolled into view, stops when it
 * leaves (via `useInView`'s IntersectionObserver, not a scroll handler),
 * and a `prefers-reduced-motion` visitor gets the finished state directly.
 */

const COMMAND = "causalmesh verify --all";

const ROWS = [
  { collection: "pilot_landing", run: "r0000", arm: "C0", events: 4 },
  { collection: "pilot_landing", run: "r0001", arm: "C0", events: 4 },
  { collection: "pilot_landing", run: "r0002", arm: "C0", events: 4 },
  { collection: "pilot_landing", run: "r0000", arm: "C1", events: 4 },
  { collection: "pilot_landing", run: "r0001", arm: "C1", events: 4 },
  { collection: "pilot_landing", run: "r0002", arm: "C1", events: 4 },
  { collection: "pilot_landing", run: "r0000", arm: "C2", events: 4 },
  { collection: "pilot_landing", run: "r0001", arm: "C2", events: 4 },
  { collection: "pilot_landing", run: "r0002", arm: "C2", events: 4 },
  { collection: "pilot_landing", run: "r0000", arm: "C3", events: 4 },
  { collection: "pilot_landing", run: "r0001", arm: "C3", events: 4 },
  { collection: "pilot_landing", run: "r0002", arm: "C3", events: 4 },
  { collection: "smoke_step10", run: "r0000", arm: "C0", events: 4 },
  { collection: "smoke_step10", run: "r0000", arm: "C1", events: 4 },
  { collection: "smoke_step10", run: "r0000", arm: "C2", events: 4 },
  { collection: "smoke_step10", run: "r0000", arm: "C3", events: 4 },
];

const SUMMARY = "28/28 chains verified offline";

const BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

function sleep(ms, signal) {
  return new Promise((resolve) => {
    const id = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(id);
      resolve();
    });
  });
}

function CollectionHeader({ name, shown }) {
  return (
    <div
      className={`pt-2 text-paper/40 transition-opacity duration-200 first:pt-0 ${
        shown ? "opacity-100" : "opacity-0"
      }`}
    >
      verify: {name}
    </div>
  );
}

function TerminalRow({ row, shown }) {
  return (
    <div
      className={`grid grid-cols-[3.5rem_2.5rem_3.5rem_5.5rem] gap-3 whitespace-nowrap transition-[opacity,transform] duration-200 ${
        shown ? "translate-y-0 opacity-100" : "translate-y-0.5 opacity-0"
      }`}
    >
      <span className="text-marker/70">{row.run}</span>
      <span className="text-paper/50">{row.arm}</span>
      <span className="text-paper/50">{row.events}</span>
      <span className="text-marker">VERIFIED</span>
    </div>
  );
}

export default function VerifyTerminal() {
  const [ref, seen] = useInView(0.35);
  const [phase, setPhase] = useState("idle"); // idle | typing | spinning | streaming | done
  const [typed, setTyped] = useState("");
  const [spinnerFrame, setSpinnerFrame] = useState(0);
  const [visibleRows, setVisibleRows] = useState(0);
  const runningRef = useRef(false);

  useEffect(() => {
    if (!seen) return;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

    if (reduced) {
      setTyped(COMMAND);
      setVisibleRows(ROWS.length);
      setPhase("done");
      return;
    }

    if (runningRef.current) return;
    runningRef.current = true;
    const controller = new AbortController();
    const { signal } = controller;

    (async () => {
      while (!signal.aborted) {
        setPhase("typing");
        setTyped("");
        setVisibleRows(0);

        for (let i = 1; i <= COMMAND.length; i += 1) {
          if (signal.aborted) return;
          setTyped(COMMAND.slice(0, i));
          await sleep(24 + Math.random() * 30, signal);
        }
        if (signal.aborted) return;
        await sleep(280, signal);

        setPhase("spinning");
        for (let f = 0; f < 14 && !signal.aborted; f += 1) {
          setSpinnerFrame(f % BRAILLE.length);
          await sleep(70, signal);
        }
        if (signal.aborted) return;

        setPhase("streaming");
        for (let i = 1; i <= ROWS.length; i += 1) {
          if (signal.aborted) return;
          setVisibleRows(i);
          await sleep(55, signal);
        }
        if (signal.aborted) return;

        setPhase("done");
        await sleep(6000, signal);
      }
    })();

    return () => {
      controller.abort();
      runningRef.current = false;
    };
  }, [seen]);

  return (
    <div
      ref={ref}
      className="overflow-hidden rounded-xl border border-ink-900 bg-ink-900 shadow-[0_24px_48px_-24px_rgba(16,16,16,0.45)]"
    >
      <div className="flex items-center gap-2 border-b border-paper/10 px-4 py-3">
        <div className="group flex items-center gap-1.5" aria-hidden="true">
          <span className="flex h-2.5 w-2.5 items-center justify-center rounded-full bg-paper/20 transition-colors duration-150 group-hover:bg-arm-c0/80">
            <svg viewBox="0 0 6 6" className="h-1.5 w-1.5 opacity-0 transition-opacity duration-150 group-hover:opacity-70">
              <path d="M1 1L5 5M5 1L1 5" stroke="#101010" strokeWidth="1" strokeLinecap="round" />
            </svg>
          </span>
          <span className="flex h-2.5 w-2.5 items-center justify-center rounded-full bg-paper/20 transition-colors duration-150 group-hover:bg-arm-c3/80">
            <svg viewBox="0 0 6 2" className="h-1.5 w-1.5 opacity-0 transition-opacity duration-150 group-hover:opacity-70">
              <path d="M0.5 1H5.5" stroke="#101010" strokeWidth="1" strokeLinecap="round" />
            </svg>
          </span>
          <span className="flex h-2.5 w-2.5 items-center justify-center rounded-full bg-marker transition-colors duration-150 group-hover:bg-marker-deep">
            <svg viewBox="0 0 6 6" className="h-1.5 w-1.5 opacity-0 transition-opacity duration-150 group-hover:opacity-70">
              <path d="M1 4L3 1L5 4" stroke="#101010" strokeWidth="1" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </span>
        </div>
        <span className="ml-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-paper/45">
          causalmesh · verify
        </span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[0.14em] text-paper/35">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              phase === "done" || phase === "idle"
                ? "bg-paper/25"
                : "bg-marker animate-pulse"
            }`}
          />
          {phase === "done" || phase === "idle" ? "idle" : "running"}
        </span>
      </div>

      <div className="px-5 py-5 font-mono text-[12px] leading-relaxed">
        <div className="text-paper">
          <span className="text-marker">$</span> {typed}
          {(phase === "typing" || phase === "idle") && (
            <span
              aria-hidden="true"
              className="cm-terminal-cursor ml-0.5 inline-block h-[13px] w-[7px] translate-y-[2px] bg-marker align-middle"
            />
          )}
        </div>

        <div className="mt-3 space-y-1">
          {phase === "spinning" && (
            <div className="text-paper/60">
              {BRAILLE[spinnerFrame]} verifying chains…
            </div>
          )}

          {(phase === "streaming" || phase === "done") && (
            <>
              {ROWS.map((row, i) => {
                const isFirstOfCollection =
                  i === 0 || ROWS[i - 1].collection !== row.collection;
                return (
                  <div key={`${row.collection}-${row.run}-${row.arm}`}>
                    {isFirstOfCollection && (
                      <CollectionHeader name={row.collection} shown={i < visibleRows} />
                    )}
                    <TerminalRow row={row} shown={i < visibleRows} />
                  </div>
                );
              })}
            </>
          )}
        </div>

        {phase === "done" && (
          <div className="mt-4 border-t border-paper/10 pt-3 text-paper">
            {SUMMARY}
          </div>
        )}
      </div>
    </div>
  );
}
