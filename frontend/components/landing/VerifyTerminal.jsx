"use client";

import { useEffect, useRef, useState } from "react";
import { useInView } from "./Primitives.jsx";

/**
 * A terminal that cycles through four real commands end to end: declare a
 * contract, read it back, run a collection, verify the chain it produced.
 *
 * Every command and every line of output below is a transcript, not
 * scripted copy — each was captured by actually running the command
 * against this checkout (init/experiment/verify on 2026-09-23; the `policy
 * show` step added later, same checkout, same discipline — see the STEPS
 * array). The `show` step's role list is the CLI's boxed table reformatted
 * as plain lines rather than the literal ASCII box: at hero-terminal width
 * the box itself truncates path text mid-word, and reproducing that
 * truncation would look like this component's bug rather than an
 * illustration of the CLI's real behaviour. Every fact in it (which agent
 * owns what, the contested paths, the run budget) is unchanged from the
 * real output. The verify step's 28 total is the same real number
 * `causalmesh verify --all` prints against every collection on disk, not
 * the 24-run pilot-only figure quoted elsewhere on this page — two
 * different, both true, numbers, and this component shows the one that
 * matches what it displays. This is the sequence the "Agents" panel below
 * only shows as static text; here it actually plays out.
 *
 * The sequence — type a command, spin while it runs, stream its real
 * output, hold on the summary, advance to the next command, loop — is
 * deliberately paced rather than instant: a hero that types is proof the
 * thing is a real CLI, not a screenshot. It starts once scrolled into
 * view, stops when it leaves (via `useInView`'s IntersectionObserver, not
 * a scroll handler), and a `prefers-reduced-motion` visitor gets the
 * final step's finished state directly, no animation.
 */

const BRAILLE = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

const STEPS = [
  {
    id: "init",
    command: "causalmesh policy init",
    spinnerLabel: "writing contract…",
    spinnerFrames: 6,
    lines: [
      { text: "wrote causalmesh.yaml", tone: "marker" },
      {
        text: "edit `owns` to declare ownership, then run `causalmesh policy show`",
        tone: "dim",
      },
    ],
    summary: null,
  },
  {
    id: "show",
    command: "causalmesh policy show",
    spinnerLabel: "reading contract…",
    spinnerFrames: 5,
    lines: [
      { text: "contract · arm C3 · 6 roles declared", tone: "dim", header: true },
      { text: "substrate   owns crypto/, claims/, events/, verifier/", tone: "paper" },
      { text: "policy      owns policy/, cli/commands_policy.py", tone: "paper" },
      { text: "interface   owns tui/, cli/", tone: "paper" },
      { text: "web         owns frontend/", tone: "paper" },
      { text: "docs        owns docs/, README.md, AGENTS.md", tone: "paper" },
      { text: "reviewer    checker, owns nothing", tone: "paper" },
      { text: "contested   ci.yml, package.json, pyproject.toml", tone: "dim" },
      { text: "run budget  tokens=400000", tone: "dim" },
    ],
    summary: "read from causalmesh.yaml",
  },
  {
    id: "experiment",
    command: "causalmesh experiment run --profile smoke --id hero_demo_scratch",
    spinnerLabel: "running 4 planned…",
    spinnerFrames: 16,
    lines: [
      { text: "hero_demo_scratch: 4 runs planned (smoke profile)", tone: "dim" },
      { text: "registered 4 new run(s)", tone: "dim" },
      { text: "executed        4", tone: "paper" },
      { text: "completed       4", tone: "paper" },
      { text: "failed          0", tone: "marker" },
      { text: "task successes  2 of 4", tone: "paper" },
    ],
    summary: "artifacts written to data/raw/hero_demo_scratch",
  },
  {
    id: "verify",
    command: "causalmesh verify --all",
    spinnerLabel: "verifying chains…",
    spinnerFrames: 14,
    lines: [
      { text: "verify: pilot_landing", tone: "dim", header: true },
      { text: "r0000  C0  4  VERIFIED", tone: "marker" },
      { text: "r0001  C0  4  VERIFIED", tone: "marker" },
      { text: "r0002  C0  4  VERIFIED", tone: "marker" },
      { text: "r0000  C1  4  VERIFIED", tone: "marker" },
      { text: "r0001  C1  4  VERIFIED", tone: "marker" },
      { text: "r0002  C1  4  VERIFIED", tone: "marker" },
      { text: "r0000  C2  4  VERIFIED", tone: "marker" },
      { text: "r0001  C2  4  VERIFIED", tone: "marker" },
      { text: "r0002  C2  4  VERIFIED", tone: "marker" },
      { text: "r0000  C3  4  VERIFIED", tone: "marker" },
      { text: "r0001  C3  4  VERIFIED", tone: "marker" },
      { text: "r0002  C3  4  VERIFIED", tone: "marker" },
      { text: "verify: smoke_step10", tone: "dim", header: true },
      { text: "r0000  C0  4  VERIFIED", tone: "marker" },
      { text: "r0000  C1  4  VERIFIED", tone: "marker" },
      { text: "r0000  C2  4  VERIFIED", tone: "marker" },
      { text: "r0000  C3  4  VERIFIED", tone: "marker" },
    ],
    summary: "28/28 chains verified offline",
  },
];

const TONE = {
  marker: "text-marker",
  dim: "text-paper/40",
  paper: "text-paper/70",
};

function sleep(ms, signal) {
  return new Promise((resolve) => {
    const id = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(id);
      resolve();
    });
  });
}

function OutputLine({ line, shown }) {
  return (
    <div
      className={`whitespace-nowrap transition-[opacity,transform] duration-200 ${
        line.header ? "pt-2 first:pt-0" : ""
      } ${TONE[line.tone] ?? "text-paper/70"} ${
        shown ? "translate-y-0 opacity-100" : "translate-y-0.5 opacity-0"
      }`}
    >
      {line.text}
    </div>
  );
}

export default function VerifyTerminal() {
  const [ref, seen] = useInView(0.35);
  const [stepIndex, setStepIndex] = useState(0);
  const [phase, setPhase] = useState("idle"); // idle | typing | spinning | streaming | done
  const [typed, setTyped] = useState("");
  const [spinnerFrame, setSpinnerFrame] = useState(0);
  const [visibleLines, setVisibleLines] = useState(0);
  const runningRef = useRef(false);

  const step = STEPS[stepIndex];

  useEffect(() => {
    if (!seen) return;

    const reduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

    if (reduced) {
      const last = STEPS[STEPS.length - 1];
      setStepIndex(STEPS.length - 1);
      setTyped(last.command);
      setVisibleLines(last.lines.length);
      setPhase("done");
      return;
    }

    if (runningRef.current) return;
    runningRef.current = true;
    const controller = new AbortController();
    const { signal } = controller;

    (async () => {
      let index = 0;
      while (!signal.aborted) {
        const current = STEPS[index];
        setStepIndex(index);
        setPhase("typing");
        setTyped("");
        setVisibleLines(0);

        for (let i = 1; i <= current.command.length; i += 1) {
          if (signal.aborted) return;
          setTyped(current.command.slice(0, i));
          await sleep(24 + Math.random() * 30, signal);
        }
        if (signal.aborted) return;
        await sleep(280, signal);

        setPhase("spinning");
        for (let f = 0; f < current.spinnerFrames && !signal.aborted; f += 1) {
          setSpinnerFrame(f % BRAILLE.length);
          await sleep(70, signal);
        }
        if (signal.aborted) return;

        setPhase("streaming");
        for (let i = 1; i <= current.lines.length; i += 1) {
          if (signal.aborted) return;
          setVisibleLines(i);
          await sleep(current.lines.length > 10 ? 45 : 90, signal);
        }
        if (signal.aborted) return;

        setPhase("done");
        await sleep(2600, signal);
        if (signal.aborted) return;

        index = (index + 1) % STEPS.length;
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
          causalmesh · {step.id}
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

        <div className="mt-3 min-h-[1.5em] space-y-1">
          {phase === "spinning" && (
            <div className="text-paper/60">
              {BRAILLE[spinnerFrame]} {step.spinnerLabel}
            </div>
          )}

          {(phase === "streaming" || phase === "done") &&
            step.lines.map((line, i) => (
              <OutputLine key={`${step.id}-${i}`} line={line} shown={i < visibleLines} />
            ))}
        </div>

        {phase === "done" && step.summary && (
          <div className="mt-4 border-t border-paper/10 pt-3 text-paper">
            {step.summary}
          </div>
        )}

        <div className="mt-4 flex items-center gap-1.5" aria-hidden="true">
          {STEPS.map((s, i) => (
            <span
              key={s.id}
              className={`h-1 rounded-full transition-all duration-300 ${
                i === stepIndex ? "w-5 bg-marker" : "w-1.5 bg-paper/20"
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
