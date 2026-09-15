"use client";

import { useCallback, useEffect, useState } from "react";
import { armResult } from "@/lib/landing/data.js";
import { ChevronLeft, ChevronRight, Pause, Play } from "./Icons.jsx";
import { useInView } from "./Primitives.jsx";

/**
 * THE FOCAL MOMENT: the trade-off plotting itself.
 *
 * Cost on x, success rate on y. Every coordinate is a measured value from
 * data/raw/pilot_landing.
 *
 * Four geometry problems the first version had, all visible on screen:
 *
 * 1. C0 (0 bytes, 0% success) mapped exactly onto the axis line, so its
 *    callout was struck through by the axis. The plot area now stops well
 *    above the axis and the origin sits inside it.
 * 2. The callout was absolutely positioned at the point and overflowed the
 *    container on the right and bottom. It now flips side and vertical
 *    anchor based on where the point actually is.
 * 3. C2 and C3 share 196 bytes, and C2 and C1 share a 100% rate, so pairs
 *    of dots collided. Colliding points are now nudged apart by a fixed
 *    offset and the connector line makes the pairing legible.
 * 4. The shaded region was drawn from the origin to the active point,
 *    which for C0 is a zero-area sliver and for C1 is nearly the whole
 *    plot. It is now a fixed quadrant marking "cheap and effective", which
 *    is a claim about the space rather than about whichever point happens
 *    to be selected.
 */

const ARM_META = {
  C0: { label: "Isolated", note: "no peer information" },
  C2: { label: "Metadata", note: "bounded window" },
  C1: { label: "Transcript", note: "unbounded history" },
  C3: { label: "Metadata + claims", note: "enforced write leases" },
};

// Plotted in cost order, which is also the order the sequence lands them.
const ORDER = ["C0", "C2", "C1", "C3"];

const DOT = {
  C0: "bg-arm-c0",
  C1: "bg-arm-c1",
  C2: "bg-marker-deep",
  C3: "bg-arm-c3",
};

// Plot area in viewBox units. Inset on every side so no point can land on
// an axis, and so a callout has somewhere to go.
const PLOT = { left: 10, right: 88, top: 12, bottom: 76 };

export default function Chart() {
  const [ref, seen] = useInView(0.35);
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const [drawn, setDrawn] = useState(0);

  const raw = ORDER.map((id) => {
    const r = armResult(id);
    return {
      id,
      ...ARM_META[id],
      bytes: r.mean_coordination_bytes,
      rate: r.success_rate,
      runs: r.runs,
      successes: r.successes,
    };
  });

  const maxBytes = Math.max(...raw.map((p) => p.bytes), 1);

  const x = (bytes) =>
    PLOT.left + (bytes / maxBytes) * (PLOT.right - PLOT.left);
  const y = (rate) => PLOT.bottom - rate * (PLOT.bottom - PLOT.top);

  // Separate colliding points. C2/C3 share a cost and C2/C1 share a rate,
  // so without this two dots sit on top of each other and the chart looks
  // like it lost a value.
  const points = raw.map((p, i) => {
    const collides = raw.some(
      (q, j) => j < i && Math.abs(q.bytes - p.bytes) < 1 && Math.abs(q.rate - p.rate) < 0.01
    );
    return { ...p, px: x(p.bytes), py: y(p.rate) + (collides ? 4 : 0) };
  });

  const reduced =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

  useEffect(() => {
    if (!seen) return;
    if (reduced) {
      setDrawn(ORDER.length);
      return;
    }
    let n = 0;
    const timer = setInterval(() => {
      n += 1;
      setDrawn(n);
      if (n >= ORDER.length) clearInterval(timer);
    }, 300);
    return () => clearInterval(timer);
  }, [seen, reduced]);

  useEffect(() => {
    if (!seen || paused || reduced || drawn < ORDER.length) return;
    const timer = setInterval(
      () => setActive((i) => (i + 1) % ORDER.length),
      3000
    );
    return () => clearInterval(timer);
  }, [seen, paused, reduced, drawn]);

  const onKeyDown = useCallback((event) => {
    const next = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[
      event.key
    ];
    if (!next) return;
    event.preventDefault();
    setActive((i) => (i + next + ORDER.length) % ORDER.length);
    setPaused(true);
  }, []);

  const current = points[active];
  const complete = drawn >= ORDER.length;

  // The callout flips to whichever side has room, so it can never overflow
  // the plot or sit under the axis.
  const calloutRight = current.px > 52;
  const calloutBelow = current.py < 26;

  return (
    <figure
      ref={ref}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      className="relative m-0"
    >
      <figcaption className="mb-3 text-[12.5px] text-ink-600">
        Higher success rate (runs passed)
      </figcaption>

      <div
        role="group"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onFocus={() => setPaused(true)}
        onBlur={() => setPaused(false)}
        aria-label="Coordination cost against success rate for four arms. Use arrow keys to move between them."
        className="relative aspect-[4/3] w-full outline-none focus-visible:ring-2 focus-visible:ring-marker-deep focus-visible:ring-offset-4 focus-visible:ring-offset-paper sm:aspect-[16/11]"
      >
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="absolute inset-0 h-full w-full"
          aria-hidden="true"
        >
          {/* Gridlines at 0 / 25 / 50 / 75 / 100 percent success. */}
          {[0, 0.25, 0.5, 0.75, 1].map((rate) => (
            <line
              key={rate}
              x1={PLOT.left - 5}
              x2={PLOT.right + 6}
              y1={y(rate)}
              y2={y(rate)}
              stroke="#e8e8e6"
              strokeWidth="0.35"
            />
          ))}

          {/* The claim about the space: cheap and effective. Fixed, so it
              describes the quadrant rather than tracking the selection. */}
          <rect
            x={PLOT.left - 5}
            y={y(1) - 4}
            width={x(maxBytes * 0.62) - PLOT.left + 5}
            height={y(0.62) - y(1) + 4}
            fill="#8ce619"
            opacity={seen ? 0.13 : 0}
            style={{ transition: "opacity 900ms cubic-bezier(0.16,1,0.3,1)" }}
          />

          {/* C2 and C3 share a cost; the tie line says so. */}
          <line
            x1={x(196)}
            x2={x(196)}
            y1={y(1)}
            y2={y(0.5) + 4}
            stroke="#b4b4b4"
            strokeWidth="0.35"
            strokeDasharray="1.5 1.5"
            opacity={complete ? 1 : 0}
            style={{ transition: "opacity 500ms ease" }}
          />

          {/* Guides to the active point. */}
          <line
            x1={current.px}
            x2={current.px}
            y1={current.py}
            y2={PLOT.bottom + 6}
            stroke="#6fbe0f"
            strokeWidth="0.4"
            strokeDasharray="2 2"
            opacity={complete ? 0.85 : 0}
            style={{ transition: "opacity 400ms ease" }}
          />
          <line
            x1={PLOT.left - 5}
            x2={current.px}
            y1={current.py}
            y2={current.py}
            stroke="#6fbe0f"
            strokeWidth="0.4"
            strokeDasharray="2 2"
            opacity={complete ? 0.85 : 0}
            style={{ transition: "opacity 400ms ease" }}
          />

          {/* Axis, drawn left to right, well below every point. */}
          <line
            x1={PLOT.left - 5}
            x2={PLOT.right + 6}
            y1={PLOT.bottom + 6}
            y2={PLOT.bottom + 6}
            stroke="#101010"
            strokeWidth="0.5"
            pathLength="1"
            strokeDasharray="1"
            strokeDashoffset={seen ? 0 : 1}
            style={{
              transition: "stroke-dashoffset 900ms cubic-bezier(0.16,1,0.3,1)",
            }}
          />
        </svg>

        {/* Y-axis labels */}
        {[
          [1, "100%"],
          [0.5, "50%"],
          [0, "0%"],
        ].map(([rate, text]) => (
          <span
            key={text}
            style={{ top: `${y(rate)}%`, left: 0 }}
            className={`pointer-events-none absolute -translate-y-1/2 font-mono text-[10px] tabular-nums text-ink-400 transition-opacity duration-700 ${
              seen ? "opacity-100" : "opacity-0"
            }`}
          >
            {text}
          </span>
        ))}

        {points.map((p, i) => {
          const isActive = i === active;
          const landed = i < drawn;
          return (
            <button
              key={p.id}
              type="button"
              tabIndex={-1}
              onClick={() => {
                setActive(i);
                setPaused(true);
              }}
              aria-label={`${p.id}, ${p.label}: ${p.successes} of ${p.runs} runs passed at ${p.bytes} bytes`}
              aria-pressed={isActive}
              style={{
                left: `${p.px}%`,
                top: `${p.py}%`,
                transitionDelay: landed ? "0ms" : `${i * 60}ms`,
              }}
              className={`absolute z-10 -translate-x-1/2 -translate-y-1/2 rounded-full p-1 transition-all duration-500 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                landed ? "scale-100 opacity-100" : "scale-50 opacity-0"
              }`}
            >
              <span
                className={`block rounded-full transition-all duration-300 ${
                  DOT[p.id]
                } ${
                  isActive
                    ? "h-3.5 w-3.5 ring-[7px] ring-marker/30"
                    : "h-2.5 w-2.5 hover:scale-125"
                }`}
              />
            </button>
          );
        })}

        {/* Callout, anchored away from the plot edges. */}
        <div
          style={{
            left: `${current.px}%`,
            top: `${current.py}%`,
            transform: `translate(${calloutRight ? "calc(-100% - 18px)" : "18px"}, ${
              calloutBelow ? "8px" : "calc(-100% - 8px)"
            })`,
          }}
          className={`pointer-events-none absolute z-20 transition-opacity duration-500 ${
            complete ? "opacity-100" : "opacity-0"
          } ${calloutRight ? "text-right" : "text-left"}`}
        >
          <div className="whitespace-nowrap text-[15px] font-medium leading-tight text-ink-900">
            {current.id} &middot; {current.label}
          </div>
          <div className="mt-1 whitespace-nowrap text-[13px] leading-tight text-marker-deep">
            {current.successes}/{current.runs} passed &middot; {current.bytes} B
          </div>
          <div className="mt-0.5 whitespace-nowrap text-[12px] leading-tight text-ink-500">
            {current.note}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between gap-4">
        <span className="text-[12.5px] text-ink-600">
          Lower coordination cost (bytes per run)
        </span>
        <div className="flex items-center gap-0.5 text-ink-500">
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            aria-label={paused ? "Resume cycling arms" : "Pause cycling arms"}
            className="p-1.5 transition-colors hover:text-ink-900"
          >
            {paused ? <Play /> : <Pause />}
          </button>
          <button
            type="button"
            onClick={() => {
              setActive((i) => (i - 1 + ORDER.length) % ORDER.length);
              setPaused(true);
            }}
            aria-label="Previous arm"
            className="p-1.5 transition-colors hover:text-ink-900"
          >
            <ChevronLeft />
          </button>
          <button
            type="button"
            onClick={() => {
              setActive((i) => (i + 1) % ORDER.length);
              setPaused(true);
            }}
            aria-label="Next arm"
            className="p-1.5 transition-colors hover:text-ink-900"
          >
            <ChevronRight />
          </button>
        </div>
      </div>
    </figure>
  );
}
