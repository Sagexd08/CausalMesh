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
