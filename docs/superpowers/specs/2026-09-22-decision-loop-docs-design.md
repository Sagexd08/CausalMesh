# Design: fold the decision-loop framing into docs and the landing page

**Date:** 2026-09-22
**Status:** approved for implementation

## Context

The user pasted a full product spec for a hypothetical "CausalMesh" product built
around an embedded decision engine called "Jev," TypeScript throughout, with Claude
Code and Codex as the two supported coding agents, and asked to "enhance the current
spec and move and ship this integrate both and update the frontend too."

The actual repository is a Python research vertical slice (`src/causalmesh/`) plus a
Next.js documentation/landing site (`frontend/`). It already has:

- `docs/PLAN.md` — authoritative record of what's built (steps 0–10 done)
- `docs/FRAMEWORK-PLAN.md` — a more rigorous, evidence-cited "framework" repositioning
  written 2026-09-15, explicitly marked "proposed, not built"
- `docs/backlog.md` — honest record of declared non-goals and their status
- A mature, editorial-style landing page with sections (`Framework.jsx`, `Routing.jsx`,
  `Integrity.jsx`, etc.) that already cover most of the pasted spec's core thesis (the
  four-plane model: contract / enforcement / evidence / measurement)

No "Jev," no Codex, no TypeScript core exist in this repo, and building them would mean
discarding real, tested Python infrastructure to match a spec that was never validated
against this codebase.

Resolved with the user: treat the pasted spec as a positioning/vision document. Extract
the genuinely new ideas it contributes beyond what `FRAMEWORK-PLAN.md` already argues,
and fold those into docs and frontend copy — without renaming anything to "Jev," without
a TypeScript rewrite, and without touching `src/causalmesh/` Python code.

## What the pasted spec adds beyond `FRAMEWORK-PLAN.md`

`FRAMEWORK-PLAN.md` already covers: the four-plane architecture, the three agent kinds,
the contract format, the adversarial/integrity story, and compliance-export as a
"strong fit — build" item. Comparing line by line, the spec's genuinely new content is:

1. **A typed decision taxonomy** — `classify`, `select_agent`, `recover`, `accept` — as
   the shape enforcement takes *over time* within one run, not just a single gate check.
   `FRAMEWORK-PLAN.md` describes the gate as an allow/refuse checkpoint; it doesn't
   describe the loop of decisions a run makes as it progresses (classify the task, pick
   an agent, recover from failure, decide acceptance).
2. **An explicit acceptance decision** (`ACCEPT` / `REJECT` / `HUMAN_REVIEW`) as a
   named, evidence-gated output distinct from "the agent said done."
3. **Agent handoff on recovery** — when execution moves from one agent to another after
   a failure, a signed package carrying the task, repo state, diff, test results, and
   prior decisions, so the second agent inherits execution state rather than starting
   cold.
4. **Causal edges** as a relationship layer over the existing hash chain (`caused`,
   `required`, `recovered`, `superseded`, ...) — distinct from the chain's raw sequence
   order, and useful for answering "which decision caused this write" as a query rather
   than a manual scan.
5. **Three named audit properties** — Integrity (did the record change?), Provenance
   (who emitted it?), Completeness (did we capture everything required?) — as explicitly
   distinct guarantees. `Integrity.jsx` already demonstrates integrity verification in
   detail; naming provenance and completeness as separate, not-yet-fully-answered
   properties sharpens rather than duplicates that section.

These five ideas are concrete enough to add to `docs/backlog.md` as honestly-scoped,
not-yet-built items, and are worth a short new subsection in `FRAMEWORK-PLAN.md` and one
new landing-page section.

## Changes

### 1. `docs/FRAMEWORK-PLAN.md`

Add a new subsection **"The decision loop"** immediately after "The four planes" in
§2 (The architecture). Content:

- States the four typed decisions (`classify`, `select_agent`, `recover`, `accept`) as
  the shape the Enforcement plane takes across a run's lifetime, not a fifth plane.
- Explicit `ACCEPT` / `REJECT` / `HUMAN_REVIEW` framing for acceptance, tied to evidence
  rather than agent self-report.
- One paragraph on agent handoff as what `recover` produces when it switches agents.
- Marked "not built" consistent with the rest of the document's honesty discipline —
  this is a plan addition, not a status change.

Add a short subsection **"Three audit properties"** in §5 (Complementary features),
next to the existing compliance-export bullet, naming Integrity / Provenance /
Completeness as distinct guarantees and noting which the shipped chain already answers
(integrity, via the adversarial battery) versus which remain open (completeness — did
instrumentation capture every required event; discussed but not measured).

Both additions follow the doc's existing citation-free, first-person-plan voice — no
new external sources needed since these are structural/naming additions, not empirical
claims.

### 2. `docs/backlog.md`

Add three entries, following the file's existing format (Status / Why / What it would
take):

- **Explicit acceptance decision object** — today, run success is read off verifier
  results directly; there's no standalone `ACCEPT`/`REJECT`/`HUMAN_REVIEW` record in the
  chain. Status: not built. Ties to the existing memory note that §74 needs a
  contested-path task before an acceptance gate is meaningful to test.
- **Agent handoff package on recovery** — `recover` as a decision type doesn't exist
  yet; there's currently one agent kind exercised per run, so "switch agents mid-run" has
  no handoff format to design against yet. Status: not built, blocked on multi-agent
  recovery existing at all.
- **Causal edges over the chain** — the chain already gives total order and hash
  linkage; it does not currently store typed relationships (`caused`, `required`, ...)
  between events, so "which decision caused this write" requires manually reading the
  chain rather than querying an edge. Status: not built.

### 3. Frontend — new `DecisionLoop.jsx` section

New file `frontend/components/landing/DecisionLoop.jsx`, inserted into
`frontend/app/page.tsx` immediately after `<Framework />`.

- Reuses existing primitives (`Section`, `Mark`, `useInView` from `Primitives.jsx`) and
  the same visual language as `Routing.jsx` (a small step-through diagram) and
  `Framework.jsx` (status pills for built vs. planned).
- Shows the four decisions as a small horizontal/vertical stepper:
  `classify → select_agent → recover → accept`, each with a one-line description and a
  "planned" status pill — matching how `Framework.jsx` labels the payment and autonomous
  lanes as planned rather than claiming they're built.
- Copy stays consistent with the rest of the page: no invented run numbers, no claim
  this is measured or shipped. Explicitly says this is the planned shape of the
  Enforcement plane, linking conceptually back to the `Framework` section's four planes
  rather than introducing a fifth plane.
- No new dependencies, no new visual system — plain Tailwind classes matching
  `Routing.jsx`'s existing patterns.

## Out of scope

- No changes to `src/causalmesh/` Python package.
- No renaming to "Jev," no TypeScript core, no Codex adapter.
- No claim that any of this is built, measured, or shipped — everything added is
  explicitly framed as planned, matching the existing documents' honesty discipline.

## Testing / verification

- Docs: read-through for internal consistency with `PLAN.md` and existing
  `FRAMEWORK-PLAN.md` claims; no other docs reference the four-decision taxonomy so
  there's nothing to reconcile beyond that.
- Frontend: `npm run build` (or `next build`) in `frontend/` to confirm the new section
  compiles and the page renders without errors; visually inspect the section is legible
  at desktop and mobile widths, consistent with the rest of the page's responsive
  behavior.
