# Design: real Jev adapter, plus decision-loop framing in docs and the landing page

**Date:** 2026-09-22
**Status:** approved for implementation (revised after confirming Jev is a real product)

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

No Codex, no TypeScript core exist in this repo, and building them would mean
discarding real, tested Python infrastructure to match a spec that was never validated
against this codebase. That part of the reconciliation stands as originally decided.

**Revision: Jev is real, not spec flavor text.** Web search confirms TypeSafe AI
shipped Jev on 2026-09-15 as a "System One" model: it takes program state and a set of
typed `Choice` / `Score` / `Noul` questions and returns calibrated, probabilistic
answers in one parallel pass — no text generation, so it cannot hallucinate an answer
outside the given options. Confirmed API surface (converging across multiple
independent sources): `POST https://api.typesafe.ai/v1/systemone`, `Authorization:
Bearer <TYPESAFE_API_KEY>`, JSON body carrying state plus a `questions` map; response
carries typed answers with probabilities and confidence. Given that, the user asked to
actually integrate it, not just cite it.

Resolved with the user across three follow-up questions:

1. Treat the TypeScript/Codex/product-spec framing as positioning inspiration only —
   no rewrite, no Codex adapter. (Unchanged from the original decision.)
2. Build a **real** Jev adapter in `src/causalmesh/` — an HTTP client plus typed
   request/response wrappers, not just documentation.
3. **Scope the wiring honestly.** `select_agent` and `recover` (retry/switch/escalate)
   presuppose multi-agent orchestration that does not exist yet — `scheduler/states.py`
   runs exactly one agent per run today, with no agent-switch transition in its state
   machine. Wiring those in now would be scope creep disguised as integration. Further,
   `tasks/definition.py`'s `TaskFamily` is fixed, YAML-declared data — the codebase's
   own stated principle (§35/§36, mirrored in why `AgentRole.owns`/`depends_on` are
   declared rather than inferred) is that task properties are declared, not inferred,
   so runs stay reproducible and hash-pinned. Wiring a probabilistic classifier into
   that path would cut against the codebase's own architecture. So: **build and prove
   the adapter against the real API; wire it into nothing yet.** Document the natural
   future consumers (`classify` as advisory metadata, `select_agent`/`recover` once
   multi-agent orchestration exists) as backlog items, not code.

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

### 0. `src/causalmesh/jev/` — real Jev adapter (new)

Follows the existing `adapters/` conventions exactly (`transport.py`'s `HttpTransport`,
`clients.py`'s dataclass-with-`__post_init__`-and-`_require` pattern) rather than
inventing a new HTTP layer:

- **`transport.py`** (or reuse `adapters.transport.HttpTransport` directly — it is
  already provider-agnostic: base URL, bearer key, JSON POST, typed `TransportError`).
  Jev's endpoint is a single fixed path (`v1/systemone`) rather than a family of
  endpoints, so this may need nothing new here at all; confirmed during implementation.
- **`client.py`** — `JevClient` dataclass: `api_key: str | None = None`,
  `base_url: str = "https://api.typesafe.ai/v1"`, `timeout_s: float = 30.0` (Jev is
  40–200x faster than a frontier LLM call per TypeSafe's own claims, so a chat-completion
  timeout would be far too generous here). `__post_init__` requires
  `TYPESAFE_API_KEY` via the existing `_require`-style helper — no silent unauthenticated
  fallback, matching `OpenAIClient`.
- **`questions.py`** — typed request builders for the three primitives:
  - `Choice(id, prompt, options: list[str])`
  - `Score(id, prompt, criteria: list[str])`
  - `Noul(id, prompt)`
  Each has a `to_dict()` matching the wire shape TypeSafe documents (state + a
  `questions` map keyed by question id, each entry carrying its type and prompt/options
  or prompt/criteria).
- **`response.py`** — parses the typed answer back: `ChoiceAnswer` (selected option,
  probability distribution, confidence), `ScoreAnswer` (level, per-level probabilities,
  confidence), `NoulAnswer` (probability). A `JevAnswer` union/dataclass keeps the
  parsing in one place rather than scattering `decoded["answers"][...]` reads across
  call sites.
- **`__init__.py`** exports `JevClient`, `Choice`, `Score`, `Noul`, `JevAnswer`, and the
  answer dataclasses — mirroring `adapters/__init__.py`'s export style.

**Testing**, matching `tests/integration/test_model_adapters.py`'s existing pattern of
real HTTP against a fake local server for the always-on suite:

- `tests/unit/test_jev.py` — request-building and response-parsing tests with no
  network: given a canned Jev-shaped JSON response, assert `ChoiceAnswer`/`ScoreAnswer`/
  `NoulAnswer` parse correctly; given a `Choice`/`Score`/`Noul` question, assert
  `to_dict()` matches the documented wire shape.
- `tests/integration/test_jev_live.py` — a **real** network call to
  `https://api.typesafe.ai/v1/systemone`, gated behind `TYPESAFE_API_KEY` being set
  (skipped otherwise, same convention as any test that needs a real provider key in
  this repo). Sends one small Choice question with an unambiguous answer (e.g. "pick
  the smaller number" between two options) and asserts the response parses into a
  `ChoiceAnswer` with the expected option selected. This is the "prove it against the
  real API" step, not a mock.

No wiring into `tasks/`, `scheduler/`, or `policy/gate.py` this session — see the
Context section above for why. The adapter is complete and tested standing alone.

### 1. `docs/FRAMEWORK-PLAN.md`

Add a new subsection **"The decision loop"** immediately after "The four planes" in
§2 (The architecture). Content:

- States the four typed decisions (`classify`, `select_agent`, `recover`, `accept`) as
  the shape the Enforcement plane takes across a run's lifetime, not a fifth plane.
- Names Jev (TypeSafe AI) by name as the reference implementation for what a typed
  decision engine in this role looks like: state in, a typed `Choice`/`Score`/`Noul`
  question out, a calibrated probability back — cites it as evidence the shape is
  implementable cheaply today, not as a dependency the project has adopted.
- States plainly what exists today: a tested `JevClient` adapter
  (`src/causalmesh/jev/`) that can ask any Choice/Score/Noul question against the real
  API, and nothing in the runtime calls it yet. The gate (`policy/gate.py`) remains
  fully deterministic rule evaluation; `select_agent`/`recover` have no home until
  multi-agent orchestration exists in the scheduler.
- Explicit `ACCEPT` / `REJECT` / `HUMAN_REVIEW` framing for acceptance, tied to evidence
  rather than agent self-report.
- One paragraph on agent handoff as what `recover` would produce when it switches
  agents, once that exists.
- Marked "not built" (beyond the adapter itself) consistent with the rest of the
  document's honesty discipline — this is a plan addition, not a status change.

Add a short subsection **"Three audit properties"** in §5 (Complementary features),
next to the existing compliance-export bullet, naming Integrity / Provenance /
Completeness as distinct guarantees and noting which the shipped chain already answers
(integrity, via the adversarial battery) versus which remain open (completeness — did
instrumentation capture every required event; discussed but not measured).

Both additions follow the doc's existing citation-free, first-person-plan voice — no
new external sources needed since these are structural/naming additions, not empirical
claims.

### 2. `docs/backlog.md`

Add four entries, following the file's existing format (Status / Why / What it would
take):

- **Jev decision engine — adapter built, not wired.** Status: `JevClient` and the
  Choice/Score/Noul request/response types exist in `src/causalmesh/jev/`, tested unit
  and (when `TYPESAFE_API_KEY` is set) against the real `api.typesafe.ai` endpoint.
  Nothing in the runtime calls it. Why: every decision point that exists today —
  `TaskFamily`, `check_sensitivity`'s verdict, the gate's rules — is deliberately
  deterministic, for the reproducibility reasons §35/§36 already state; there was no
  decision point this session where swapping determinism for a calibrated probability
  was the right trade. What it would take: a concrete future decision that is
  genuinely uncertain given available state (the leading candidate is `recover`:
  retry-same-agent vs. switch-agent vs. escalate, once multi-agent runs exist) rather
  than retrofitting Jev onto a decision that already has a correct deterministic answer.
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
  this is measured or shipped. Names Jev as the reference decision engine (matching the
  updated `FRAMEWORK-PLAN.md` language) and states plainly that the adapter exists and
  is tested, but nothing in the runtime calls it yet — the same "measured" vs "planned"
  status-pill pattern `Framework.jsx` already uses, applied honestly here: this lane is
  "adapter built" not "measured."
- No new dependencies, no new visual system — plain Tailwind classes matching
  `Routing.jsx`'s existing patterns.

## Out of scope

- No changes to `tasks/`, `scheduler/`, or `policy/gate.py` — the Jev adapter is built
  and tested standing alone, not wired into any runtime decision this session.
- No TypeScript core, no Codex adapter, no rewrite of `src/causalmesh/`'s existing
  Python agent adapters (OpenAI/Anthropic/Local/Mock).
- No claim that Jev-driven decisions are built, measured, or shipped in the runtime —
  only the adapter itself is real and tested; everything else added is explicitly
  framed as planned, matching the existing documents' honesty discipline.

## Testing / verification

- `src/causalmesh/jev/`: `pytest tests/unit/test_jev.py` for request/response parsing
  with no network; `pytest tests/integration/test_jev_live.py` (requires
  `TYPESAFE_API_KEY`, skipped otherwise) as the real-API proof.
- Docs: read-through for internal consistency with `PLAN.md` and existing
  `FRAMEWORK-PLAN.md` claims; no other docs reference the four-decision taxonomy or Jev
  by name so there's nothing else to reconcile.
- Frontend: `npm run build` (or `next build`) in `frontend/` to confirm the new section
  compiles and the page renders without errors; visually inspect the section is legible
  at desktop and mobile widths, consistent with the rest of the page's responsive
  behavior.
