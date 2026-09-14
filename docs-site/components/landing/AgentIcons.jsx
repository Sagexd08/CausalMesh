/**
 * Marks for the coding agents CausalMesh can drive.
 *
 * Drawn from scratch at 24x24 as simplified geometric marks, not traced
 * brand logos: this project has no licence to reproduce anyone's
 * trademark, and a wrong-but-recognisable logo is worse than an honest
 * abstraction. Each is a distinct silhouette so the grid reads as a set of
 * different things rather than a row of identical squares.
 *
 * They share one stroke weight and one 24x24 frame, which is what makes a
 * set of marks an icon system rather than a pile of clip art.
 */

const frame = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": "true",
};

/** Radiating burst. */
export function ClaudeMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <path d="M12 3.5v17M3.5 12h17M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

/** Interlocking ring. */
export function CodexMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5c3 2.6 3 14 0 17M12 3.5c-3 2.6-3 14 0 17" />
    </svg>
  );
}

/** Terminal caret in a frame. */
export function OpenCodeMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <path d="M7.5 10l2.5 2.5-2.5 2.5M12.5 15.5h4" />
    </svg>
  );
}

/** Nested chevrons. */
export function CursorMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <path d="M12 3.2l8 4.6v8.4l-8 4.6-8-4.6V7.8l8-4.6Z" />
      <path d="M12 12l8-4.2M12 12v8.8M12 12L4 7.8" />
    </svg>
  );
}

/** Aider: layered lines. */
export function AiderMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <path d="M4 8.5h16M4 13h10M4 17.5h13" />
      <circle cx="18.5" cy="13" r="2" />
    </svg>
  );
}

/** Cline: branch. */
export function ClineMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <circle cx="7" cy="6" r="2.3" />
      <circle cx="7" cy="18" r="2.3" />
      <circle cx="17" cy="12" r="2.3" />
      <path d="M7 8.3v7.4M9.2 6.9c4 .7 5.2 2.4 5.6 4.1M9.2 17.1c4-.7 5.2-2.4 5.6-4.1" />
    </svg>
  );
}

/** Goose: chevron pair. */
export function GooseMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <path d="M4 9l8 6 8-6M4 14.5l8 6 8-6" />
    </svg>
  );
}

/** Continue: arrow through a gate. */
export function ContinueMark({ className = "h-5 w-5" }) {
  return (
    <svg {...frame} className={className}>
      <path d="M3.5 12h13M12 7.5l4.5 4.5L12 16.5" />
      <path d="M20 4.5v15" />
    </svg>
  );
}

export const AGENT_MARKS = [
  ["Claude Code", ClaudeMark],
  ["Codex", CodexMark],
  ["Cursor", CursorMark],
  ["OpenCode", OpenCodeMark],
  ["Aider", AiderMark],
  ["Cline", ClineMark],
  ["Goose", GooseMark],
  ["Continue", ContinueMark],
];
