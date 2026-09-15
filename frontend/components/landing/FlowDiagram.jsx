"use client";

/**
 * The fleet -> gate -> repo diagram for Architecture.jsx.
 *
 * Replaces the plain "fleet / every call is accounted for / repo" text
 * header with the mechanism actually drawn: three agents send a write, the
 * gate consults the claim registry, two writes land in the repo and one is
 * refused. Same shape the reference brought (curved connectors, reserved
 * label space, an arrowhead at every receiving end) rendered in this site's
 * own tokens rather than its colours.
 *
 * Geometry rules, matched to the reference:
 *  - flow reads left-to-right, always arrowheaded at the receiving end
 *  - connectors are cubic curves, not right angles
 *  - every label sits in reserved space, never over a stroke or fill
 *  - 1px strokes; ink + the marker/arm accents only
 *
 * Two layouts ship: wide (desktop) and narrow (mobile), because scaling the
 * wide viewBox down would shrink 10px labels to unreadable. Animation is
 * paused until the diagram is on screen (`useInView`), and CSS handles the
 * actual draw so an off-screen diagram costs nothing.
 */

import { useInView } from "./Primitives.jsx";

function Defs({ id }) {
  return (
    <defs>
      <marker
        id={`${id}-arrow`}
        viewBox="0 0 9 9"
        refX="8"
        refY="4.5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path
          d="M1 1 L8 4.5 L1 8"
          fill="none"
          stroke="var(--color-ink-500)"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </marker>
      <marker
        id={`${id}-arrow-live`}
        viewBox="0 0 9 9"
        refX="8"
        refY="4.5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path
          d="M1 1 L8 4.5 L1 8"
          fill="none"
          stroke="var(--color-marker-deep)"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </marker>
      <marker
        id={`${id}-arrow-refused`}
        viewBox="0 0 9 9"
        refX="8"
        refY="4.5"
        markerWidth="7"
        markerHeight="7"
        orient="auto-start-reverse"
      >
        <path
          d="M1 1 L8 4.5 L1 8"
          fill="none"
          stroke="var(--color-arm-c0)"
          strokeWidth="1.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </marker>
    </defs>
  );
}

/**
 * One agent -> gate -> repo path, laid out on a normalized 0-1 grid so the
 * wide and narrow SVGs can each map it to their own coordinates instead of
 * duplicating the curve math.
 */
const PATHS = [
  { id: 0, agent: "agent_a", outcome: "granted" },
  { id: 1, agent: "agent_b", outcome: "granted" },
  { id: 2, agent: "agent_c", outcome: "refused" },
];

function WideDiagram({ id, live }) {
  const agentX = 8;
  const gateX = 230;
  const repoX = 452;
  const rowY = [42, 96, 150];
  const gateTop = 24;
  const gateH = 144;
  const gateMidY = gateTop + gateH / 2;

  return (
    <svg
      className="fd-wide"
      viewBox="0 0 520 214"
      role="img"
      aria-labelledby={`${id}-t ${id}-d`}
      style={{ width: "100%", height: "auto" }}
    >
      <title id={`${id}-t`}>Three agents, one gate, one refusal</title>
      <desc id={`${id}-d`}>
        Three agents each send a write toward the repository. Every write
        passes through the gate. Two are granted and continue to the repo;
        the third targets a path it does not own and is refused, recorded
        rather than dropped.
      </desc>
      <Defs id={id} />

      {/* agents */}
      {PATHS.map((p, i) => (
        <g key={p.id}>
          <rect
            x={agentX}
            y={rowY[i] - 14}
            width="88"
            height="28"
            className="fd-node"
          />
          <text x={agentX + 44} y={rowY[i] + 4} textAnchor="middle" className="fd-label">
            {p.agent}
          </text>
        </g>
      ))}

      {/* agent -> gate */}
      {PATHS.map((p, i) => {
        const d = `M${agentX + 88} ${rowY[i]} C${(agentX + 88 + gateX) / 2} ${rowY[i]}, ${(agentX + 88 + gateX) / 2} ${gateMidY}, ${gateX - 6} ${gateMidY}`;
        return (
          <g key={p.id}>
            <path
              className={`fd-line fd-flow${live ? " fd-seen" : ""}`}
              style={{ transitionDelay: `${i * 140}ms` }}
              markerEnd={`url(#${id}-arrow)`}
              d={d}
            />
            <path
              className={`fd-pulse fd-pulse--in${live ? " fd-seen" : ""}`}
              style={{ animationDelay: `${i * 420}ms` }}
              d={d}
            />
          </g>
        );
      })}

      {/* gate */}
      <rect
        x={gateX}
        y={gateTop}
        width="72"
        height={gateH}
        className="fd-node fd-node--accent"
      />
      <text x={gateX + 36} y={gateMidY - 6} textAnchor="middle" className="fd-label fd-label--accent">
        Gate
      </text>
      <text x={gateX + 36} y={gateMidY + 12} textAnchor="middle" className="fd-label fd-label--dim">
        registry
      </text>

      {/* gate -> repo (granted) */}
      {PATHS.filter((p) => p.outcome === "granted").map((p, i) => {
        const d = `M${gateX + 72} ${gateMidY - 22 + i * 44} C${(gateX + 72 + repoX) / 2} ${gateMidY - 22 + i * 44}, ${(gateX + 72 + repoX) / 2} 96, ${repoX - 6} 96`;
        return (
          <g key={p.id}>
            <path
              className={`fd-line fd-line--granted fd-flow${live ? " fd-seen" : ""}`}
              style={{ transitionDelay: `${400 + i * 140}ms` }}
              markerEnd={`url(#${id}-arrow-live)`}
              d={d}
            />
            <path
              className={`fd-pulse fd-pulse--granted${live ? " fd-seen" : ""}`}
              style={{ animationDelay: `${1300 + i * 420}ms` }}
              d={d}
            />
          </g>
        );
      })}

      {/* The refusal turns back toward the agent that asked, rather than
          curling into empty space. A refused write has a destination -
          the agent is told no - and a path that ends nowhere reads as an
          unfinished stroke instead of the mechanism this diagram exists
          to show. */}
      <path
        className={`fd-line fd-line--refused fd-flow${live ? " fd-seen" : ""}`}
        style={{ transitionDelay: "680ms" }}
        markerEnd={`url(#${id}-arrow-refused)`}
        d={`M${gateX - 2} ${gateMidY + 30} C${gateX - 60} ${gateMidY + 48}, ${agentX + 130} ${rowY[2] + 34}, ${agentX + 46} ${rowY[2] + 20}`}
      />
      <text
        x={gateX - 66}
        y={rowY[2] + 44}
        textAnchor="middle"
        className="fd-label fd-label--refused"
      >
        refused, and recorded
      </text>

      {/* repo */}
      <rect
        x={repoX}
        y={rowY[1] - 26}
        width="76"
        height="52"
        className="fd-node fd-node--accent"
      />
      <text x={repoX + 38} y={rowY[1] + 4} textAnchor="middle" className="fd-label fd-label--accent">
        repo
      </text>
    </svg>
  );
}

function NarrowDiagram({ id, live }) {
  const colX = 150;
  const rowY = [16, 54, 92];
  const gateY = 132;
  const repoY = 232;

  return (
    <svg
      className="fd-narrow"
      viewBox="0 0 300 260"
      role="img"
      aria-hidden="true"
      style={{ width: "100%", height: "auto" }}
    >
      <Defs id={`${id}n`} />

      {PATHS.map((p, i) => (
        <g key={p.id}>
          <rect x={colX - 46} y={rowY[i] - 12} width="92" height="24" className="fd-node" />
          <text x={colX} y={rowY[i] + 4} textAnchor="middle" className="fd-label">
            {p.agent}
          </text>
        </g>
      ))}

      {PATHS.map((p, i) => (
        <path
          key={p.id}
          className={`fd-line fd-flow${live ? " fd-seen" : ""}`}
          style={{ transitionDelay: `${i * 140}ms` }}
          markerEnd={`url(#${id}n-arrow)`}
          d={`M${colX} ${rowY[i] + 12} C${colX} ${(rowY[i] + gateY) / 2}, ${colX} ${(rowY[i] + gateY) / 2}, ${colX} ${gateY - 16}`}
        />
      ))}

      <rect x={colX - 44} y={gateY - 14} width="88" height="28" className="fd-node fd-node--accent" />
      <text x={colX} y={gateY + 5} textAnchor="middle" className="fd-label fd-label--accent">
        Gate
      </text>

      <path
        className={`fd-line fd-line--granted fd-flow${live ? " fd-seen" : ""}`}
        style={{ transitionDelay: "460ms" }}
        markerEnd={`url(#${id}n-arrow-live)`}
        d={`M${colX} ${gateY + 14} C${colX} ${(gateY + repoY) / 2}, ${colX} ${(gateY + repoY) / 2}, ${colX} ${repoY - 18}`}
      />

      <path
        className={`fd-line fd-line--refused fd-flow${live ? " fd-seen" : ""}`}
        style={{ transitionDelay: "600ms" }}
        markerEnd={`url(#${id}n-arrow-refused)`}
        d={`M${colX + 44} ${gateY} C${colX + 90} ${gateY}, ${colX + 90} ${gateY - 40}, ${colX + 44} ${gateY - 40}`}
      />
      <text x={colX + 90} y={gateY - 50} textAnchor="middle" className="fd-label fd-label--refused">
        refused
      </text>

      <rect x={colX - 40} y={repoY - 18} width="80" height="36" className="fd-node fd-node--accent" />
      <text x={colX} y={repoY + 5} textAnchor="middle" className="fd-label fd-label--accent">
        repo
      </text>
    </svg>
  );
}

export default function FlowDiagram() {
  const [ref, seen] = useInView(0.4);

  return (
    <div ref={ref} className="fd-host">
      {/* Column labels, tied to the diagram by a rule rather than floating
          above it as three unrelated words. */}
      <div className="mb-5 flex items-center gap-3 border-b border-rule-soft pb-2 font-mono text-[10px] uppercase tracking-[0.16em] text-ink-500">
        <span>fleet</span>
        <span className="h-px flex-1 bg-rule-soft" />
        <span className="text-ink-700">every call is accounted for</span>
        <span className="h-px flex-1 bg-rule-soft" />
        <span>repo</span>
      </div>
      <WideDiagram id="fd" live={seen} />
      <NarrowDiagram id="fd" live={seen} />
    </div>
  );
}
