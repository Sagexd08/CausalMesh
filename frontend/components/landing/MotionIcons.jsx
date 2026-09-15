"use client";

/**
 * Drawn icons that animate their own meaning.
 *
 * Every icon here is authored SVG on one 1.5px stroke and a 24px grid — no
 * icon font, no emoji, no unicode glyph standing in for a mark. The set is
 * deliberately small: five icons, each naming one thing this product does,
 * because a page that ships forty icons has stopped using them to mean
 * anything.
 *
 * **The motion is the definition.** A gate icon whose bar drops is showing
 * you what a gate does; a chain icon whose links seal left-to-right is
 * showing you what hash-linking is. That is the one justification for motion
 * on an icon this size — if the movement does not carry the meaning, a
 * static mark is better and cheaper.
 *
 * Each animates on hover and once when scrolled into view, then stops.
 * Nothing loops forever: a page where every mark is permanently moving has
 * told the reader nothing about what is moving *now*, which is the same
 * reasoning the terminal monitor's own docstring records.
 *
 * `prefers-reduced-motion` removes every transition through the CSS in
 * landing.css rather than through a hook, so the icons stay correct when
 * JavaScript has not hydrated yet.
 */

import { useInView } from "./Primitives.jsx";

const BASE = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  viewBox: "0 0 24 24",
  xmlns: "http://www.w3.org/2000/svg",
  "aria-hidden": "true",
  focusable: "false",
};

/** Shared wrapper: runs the animation once on view, and again on hover. */
function Animated({ children, className = "h-6 w-6", label }) {
  const [ref, seen] = useInView(0.5);
  return (
    <span
      ref={ref}
      className={`cm-icon ${seen ? "cm-icon-seen" : ""} ${className}`}
      role={label ? "img" : undefined}
      aria-label={label}
    >
      {children}
    </span>
  );
}

/**
 * The gate. A bar drops across the path an arrow was taking.
 *
 * The product's central act, so it is the one icon that shows a refusal
 * rather than a state.
 */
export function GateIcon({ className, label }) {
  return (
    <Animated className={className} label={label}>
      <svg {...BASE}>
        {/* The track an action travels, drawn as one line the arm crosses.
            Two separate half-lines read as a broken path even before the
            arm moves. */}
        <path d="M2 16h20" className="cm-gate-track" />
        {/* The post the arm is hinged to. */}
        <path d="M6 16V7" className="cm-gate-post" />
        {/* The arm. Raised, it points up and right from the hinge at the
            post's top; dropped, it rotates down onto the track. Drawn from
            the hinge outward so the rotation origin is the hinge itself —
            an arm drawn across the middle swings out of the frame. */}
        <g className="cm-gate-arm">
          <path d="M6 7h13" />
        </g>
        <circle cx="6" cy="7" r="1.1" className="cm-gate-pivot" />
      </svg>
    </Animated>
  );
}

/**
 * The chain. Links seal in sequence, left to right.
 *
 * Hash-linking is an ordering property, so the icon animates in order. A
 * chain whose links appeared simultaneously would be drawing a set.
 */
export function ChainIcon({ className, label }) {
  return (
    <Animated className={className} label={label}>
      <svg {...BASE}>
        {/* Overlap is one stroke-width only: enough to read as linked,
            little enough that three links stay countable. At a 1px gap
            they merged into one blob. */}
        <rect x="2" y="9" width="8" height="6" rx="3" className="cm-link cm-link-1" />
        <rect x="8" y="9" width="8" height="6" rx="3" className="cm-link cm-link-2" />
        <rect x="14" y="9" width="8" height="6" rx="3" className="cm-link cm-link-3" />
      </svg>
    </Animated>
  );
}

/**
 * The signature. A stroke writes itself, then the seal closes around it.
 */
export function SignIcon({ className, label }) {
  return (
    <Animated className={className} label={label}>
      <svg {...BASE}>
        <path d="M4 16c2.5-6 4-7 5-4s2 4 3.5 1.5S16 9 20 8.5" className="cm-sign-stroke" />
        <circle cx="12" cy="12" r="9.25" className="cm-sign-seal" />
      </svg>
    </Animated>
  );
}

/**
 * The ledger. Rows fill in, and the last one is the total.
 */
export function LedgerIcon({ className, label }) {
  return (
    <Animated className={className} label={label}>
      <svg {...BASE}>
        <rect x="3.5" y="3.5" width="17" height="17" rx="2" className="cm-ledger-frame" />
        <path d="M7 9h10" className="cm-row cm-row-1" />
        <path d="M7 12.5h10" className="cm-row cm-row-2" />
        <path d="M7 16h6" className="cm-row cm-row-3" />
      </svg>
    </Animated>
  );
}

/**
 * The fleet. Four agents converging on one resource.
 *
 * The experiment's own subject, at icon scale: three paths land and the
 * fourth stops short.
 */
export function FleetIcon({ className, label }) {
  return (
    <Animated className={className} label={label}>
      <svg {...BASE}>
        <circle cx="5" cy="5" r="2" className="cm-agent cm-agent-1" />
        <circle cx="12" cy="4" r="2" className="cm-agent cm-agent-2" />
        <circle cx="19" cy="5" r="2" className="cm-agent cm-agent-3" />
        <path d="M5 7.5v3.5h14V7.5" className="cm-fleet-rail" />
        <path d="M12 6v5" className="cm-fleet-rail" />
        <rect x="8" y="14" width="8" height="6" rx="1.5" className="cm-fleet-target" />
      </svg>
    </Animated>
  );
}
