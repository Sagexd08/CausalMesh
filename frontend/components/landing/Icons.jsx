/**
 * Authored SVG icons, one consistent stroke weight.
 *
 * Unicode glyphs and emoji standing in for an icon system is a craft-floor
 * refusal, and it shows: a glyph inherits the text font's metrics, so it
 * sits on the wrong baseline, changes size with the type scale, and looks
 * different on every platform. These are drawn at 24x24 with a 1.6 stroke
 * and currentColor, so they inherit intent without inheriting typography.
 */

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": "true",
};

export function ChevronRight({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

export function ChevronLeft({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className}>
      <path d="M15 6l-6 6 6 6" />
    </svg>
  );
}

export function ChevronDown({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className}>
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

export function Pause({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className}>
      <path d="M9 5v14M15 5v14" />
    </svg>
  );
}

export function Play({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className}>
      <path d="M8 5l11 7-11 7V5Z" />
    </svg>
  );
}

export function Check({ className = "h-4 w-4" }) {
  return (
    <svg {...base} className={className}>
      <path d="M4 12.5l5.2 5.2L20 7" />
    </svg>
  );
}

export function Folder({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2.4h8a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" />
    </svg>
  );
}

export function FileIcon({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className}>
      <path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9l-6-6Z" />
      <path d="M13 3v6h6" />
    </svg>
  );
}

export function Lock({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className}>
      <rect x="4.5" y="10.5" width="15" height="10" rx="2" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

export function Blocked({ className = "h-3.5 w-3.5" }) {
  return (
    <svg {...base} className={className}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M6.4 6.4l11.2 11.2" />
    </svg>
  );
}

/**
 * The menu toggle, drawn in both states.
 *
 * One component rather than two so the bars can animate between them: the
 * top and bottom rules rotate into the cross and the middle one fades,
 * which shows that the same control closes what it opened.
 */
export function MenuToggle({ open = false, className = "h-5 w-5" }) {
  return (
    <svg {...base} className={className}>
      <line
        x1="4"
        y1={open ? "12" : "7"}
        x2="20"
        y2={open ? "12" : "7"}
        style={{
          transformOrigin: "center",
          transform: open ? "rotate(45deg)" : "none",
          transition: "transform 260ms cubic-bezier(0.22,1,0.36,1), y1 200ms, y2 200ms",
        }}
      />
      <line
        x1="4"
        y1="12"
        x2="20"
        y2="12"
        style={{
          opacity: open ? 0 : 1,
          transition: "opacity 160ms ease-out",
        }}
      />
      <line
        x1="4"
        y1={open ? "12" : "17"}
        x2="20"
        y2={open ? "12" : "17"}
        style={{
          transformOrigin: "center",
          transform: open ? "rotate(-45deg)" : "none",
          transition: "transform 260ms cubic-bezier(0.22,1,0.36,1), y1 200ms, y2 200ms",
        }}
      />
    </svg>
  );
}

/**
 * The GitHub mark.
 *
 * Filled rather than stroked, unlike everything else here, because this one
 * is a brand mark and not a member of the icon set: it has an official
 * outline and redrawing it at a 1.6 stroke to match the others would make
 * it a worse likeness of the thing it identifies. Brand marks are used as
 * issued or not at all.
 */
export function GitHubMark({ className = "h-4 w-4" }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
      className={className}
    >
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}
