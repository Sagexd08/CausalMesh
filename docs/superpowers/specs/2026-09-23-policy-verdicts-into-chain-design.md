# Design: policy verdicts as signed chain events, plus an honest hero terminal

**Date:** 2026-09-23
**Status:** approved for implementation

## Context

Two independent pieces of work, requested together in the same conversation:

1. The hero terminal (`VerifyTerminal.jsx`, added earlier this session) needs visual
   polish — real macOS-style traffic-light window controls instead of plain dots, a
   more considered cursor — and a factual fix found in the same audit: `Agents.jsx`'s
   setup panel shows `causalmesh run --arm C3 --task schema_handler_widen` as example
   usage, but `causalmesh run` is not a real command. The actual CLI tree (confirmed by
   running `causalmesh --help`) is `doctor | verify | analyze | audit | watch | welcome
   | task | experiment | policy | serve | manifest | connectors`.
2. A real backend gap, picked from `docs/backlog.md`'s existing "Verdicts do not enter
   the signed chain" entry: `ContractGate` (`src/causalmesh/hooks/policy_gate.py`)
   accumulates every `Verdict` it reaches in memory and serializes them via `to_dict()`
   into a run artifact, but no `Event` is ever constructed for a verdict, so refusals
   by the policy plane are not chain evidence — they cannot be hash-linked, signed, or
   verified offline the way every other recorded fact on this project can be. The
   backlog entry states this is more than cosmetic: "the project's central claim is
   that a refusal is recorded evidence rather than a log line... until the verdict has
   an event type, the policy plane's refusals are the one kind of refusal that is not
   provable."

Investigated and confirmed directly against the code (not assumed):

- `EventType` (`src/causalmesh/events/schema.py`) is a closed `StrEnum` with a fixed
  research vocabulary (INTENT, READ, WRITE, CREATE, MODIFY, DELETE, RENAME, TEST,
  CLAIM, RELEASE, COMMIT, FAILURE). Adding a member is a normal, additive change — the
  chain's canonicalization and hashing are generic over `event_type`.
- `Event.payload` is `dict[str, Any]` with no schema constraint beyond being a dict —
  `Verdict.to_dict()` (already confirmed "chain-shaped and tested" per the backlog
  entry) can be used directly as an event's payload.
- `Relay.ingest(*, event_id, agent_id, event_type, identity, timestamp_us, paths=(),
  references=(), parent_id=None, payload=None)` is the one path onto the chain.
  Crucially: `agent_id` must have a registered key in `Relay._keypairs`, and the
  chain's signature is over that keypair — there is no existing non-agent signing
  identity for policy/system-level events.
- `Relay._participants` (used only for delivery/fan-out to other agents' inboxes) is
  set explicitly by `runner.py` (`participants=agent_ids`), so adding a new key to
  `_keypairs` does not implicitly add it to `_participants` or make it a fan-out
  recipient — the two are independent.
- `KeyPair.derive(master_seed, actor_id)` accepts any string `actor_id` and
  deterministically derives a real Ed25519 keypair — the same mechanism already used
  for every per-agent key in `runner.py`.
- `runner.py`'s `_gate_for()` constructs `ContractGate.build(...)` only when
  `config.contract_path is not None`; the arm's default gate (`AllowAllGate`/
  `ClaimGate`) is unaffected and out of scope for this change.

**The honesty constraint driving the design:** a verdict is reached by the policy
plane, not by any participating agent. Attributing it to an arbitrary existing
`agent_id` would misattribute provenance — exactly the kind of inferred-rather-than-
declared attribution this codebase's own stated principles forbid (see `EventIdentity`
and `AgentRole.owns`/`depends_on`'s "declared, not inferred" reasoning, referenced
elsewhere in this codebase's own docs). The design therefore mints a real, distinct
signing identity for the policy plane itself (`policy_gate`), rather than borrowing an
agent's key or leaving the event unsigned.

## Decisions

1. **Scope:** every verdict `ContractGate` reaches becomes a chain event — not only
   refusals. `Verdict.to_dict()` already reports `allowed`, `detail` (including
   `would_refuse` for shadow verdicts on non-enforcing arms), `reason`, `resource`, and
   `rule`; recording only refusals would silently drop the counterfactual data an
   unenforced arm's shadow-refusals represent, which is itself a measured quantity this
   project cares about (§ referenced throughout `policy_gate.py`'s own docstrings).
2. **One new event type:** `EventType.POLICY_VERDICT`. Not `POLICY_REFUSAL`, because
   scope (decision 1) includes allowed verdicts too.
3. **One new signing identity:** `"policy_gate"`, derived via `KeyPair.derive(seed,
   "policy_gate")` in `runner.py`, added to the `keypairs` dict passed to `Relay`
   alongside the per-agent keys, whenever a `ContractGate` is installed (i.e., whenever
   `config.contract_path is not None`). Not added to `participants` — it is not a
   fan-out recipient.
4. **Where the wiring happens:** in `runner.py`, after `execute_task` finishes running
   the scenario and before it returns, rather than inside `ContractGate.check()`
   itself. Reasoning: `ContractGate.check()` is a synchronous, side-effect-scoped
   method today (it appends to an in-memory list and, for claim refusals, calls the
   registry) — giving it a `Relay` dependency and making it async-aware would change
   its signature and the protocol every other `Gate` implementation satisfies. Emitting
   events from the runner, using the same `ContractGate.verdicts` list the artifact
   already reads, keeps `ContractGate` itself unchanged and additive-only.
5. **Timestamp:** the verdict object does not currently carry a timestamp. The runner
   assigns each verdict-event a monotonically increasing microsecond timestamp at
   emission time (`utc_now_micros()`), consistent with how other post-hoc event
   emission in this codebase works. This is stated as an approximation, not the exact
   moment `check()` was called — acceptable because verdict events are for provability
   of the decision and its reasoning, not for sub-microsecond timing analysis.
6. **`parent_id`:** left `None` for this change. A `POLICY_VERDICT`'s "what it was
   evaluating" is fully captured in its `payload` (the resource, the rule, the
   holder) — linking it causally to the specific tool-call event it responded to is
   exactly the "causal edges over the chain" backlog item, explicitly out of scope for
   this session per the earlier scoping conversation.
7. **Verification:** no change needed to `verifier/` — chain verification (hash
   linkage, signature checks) is generic over `event_type`, confirmed by reading how
   `EventType` is used there. A dedicated integration test proves this rather than
   asserting it.

## Frontend changes (independent of the backend work above)

### `VerifyTerminal.jsx` — real macOS-style window chrome

Replace the current three plain dots with functional-looking traffic-light buttons
(red/close, yellow/minimize, green/maximize shapes, hover states) — visual only, no
actual window behavior since this is a decorative terminal inside a web page, not a
real OS window. Colors stay within the existing palette discipline: muted at rest,
using the same `paper/`, `marker` tokens already used elsewhere in this component
rather than introducing macOS's literal red/yellow/green (which would violate this
project's single-accent-color rule).

Cursor: replace the flat `animate-pulse` block cursor with a smoother, more deliberate
blink (matching the existing `blink`-style keyframe pattern already used in the
Palisade reference this component was adapted from, translated into this project's own
timing/easing conventions — not copying Palisade's colors).

### `Agents.jsx` — fix the fabricated command

A repo-wide grep (`grep -rn "causalmesh run\b" --include="*.jsx" --include="*.tsx"
frontend/`) finds exactly one fabricated command, in `stepsFor()`'s third step:

```
causalmesh run --arm C3 --task schema_handler_widen
```

`causalmesh run` is not a real command — confirmed by running `causalmesh --help`
against this checkout; the real top-level tree is `doctor | verify | analyze | audit |
watch | welcome | task | experiment | policy | serve | manifest | connectors`. The
closest real equivalent, confirmed by running `causalmesh experiment run --help`, is:

```
causalmesh experiment run --profile smoke
```

`experiment run` does not take `--arm`/`--task` directly (those are configured through
a profile file under `configs/profiles/`, not passed inline), so the replacement copy
also drops the now-inaccurate `--arm C3 --task schema_handler_widen` framing rather
than keeping flags the real command does not accept. The step's surrounding prose
("The arm installs a channel and a gate. Nothing reads the arm name at runtime.")
stays conceptually accurate to how arms work — the fix is the literal command line
only.

The other two commands in the same panel are real and unchanged:
`causalmesh serve --agent <name>` (step 1) and the `roles:`/`owns:` YAML snippet
(step 2, not a shell command).

## Backend changes in detail

### `src/causalmesh/events/schema.py`

Add one `EventType` member:
```python
POLICY_VERDICT = "POLICY_VERDICT"
```

### `src/causalmesh/tasks/runner.py`

- In `_gate_for()` or `execute_task()` (wherever `ContractGate.build(...)` is called),
  when a contract path is given: derive `policy_keypair = KeyPair.derive(
  config.master_seed, "policy_gate")` and merge it into the `keypairs` dict passed to
  `Relay(...)`.
- After the scenario finishes executing (verdicts have accumulated on
  `gate.verdicts`), for each `Verdict` in `gate.verdicts` (when `gate` is a
  `ContractGate` — an `AllowAllGate`/`ClaimGate` has no `.verdicts` attribute and is
  unaffected), call `relay.ingest(event_id=<deterministic-per-verdict-id>,
  agent_id="policy_gate", event_type=EventType.POLICY_VERDICT,
  identity=EventIdentity(..., agent_id="policy_gate"), timestamp_us=utc_now_micros(),
  payload=verdict.to_dict())`.
- `event_id` generation: `f"{config.run_id}_verdict_{index}"` (zero-padded index over
  `enumerate(gate.verdicts)`), matching the identifier pattern
  `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$` already enforced by `_require_identifier`.

### Tests

- **Unit** (`tests/unit/test_events.py` or wherever `EventType` is already tested):
  `EventType.POLICY_VERDICT` exists, round-trips through `to_canonical_dict()`/
  canonicalization like every other member.
- **Unit** (`tests/unit/test_policy_gate.py`, already exists): constructing a
  `policy_gate` `KeyPair` via `KeyPair.derive(seed, "policy_gate")` is deterministic
  and distinct from any per-agent key derived from the same seed.
- **Integration** (new or extending an existing runner/chain integration test): run a
  task with a contract that produces at least one refusal and one allowed verdict;
  after the run, read the chain and confirm: (a) at least one `POLICY_VERDICT` event
  exists, (b) its `payload` matches the corresponding `Verdict.to_dict()`, (c) the
  event's `agent_id`/signing identity is `policy_gate`, distinct from every
  participating agent, (d) `causalmesh verify` (or the equivalent programmatic
  verifier call) reports the chain as verified with no special-casing required for the
  new event type — proving decision 7 rather than asserting it.

## `docs/backlog.md` updates

- **"Verdicts do not enter the signed chain"** — status updated from open to resolved,
  citing the new `EventType.POLICY_VERDICT`, the `policy_gate` signing identity, and
  the integration test that proves offline verification handles it.
- **"The gate is installable but not yet installed by default"** — add a note that
  verdicts now reach the chain when the gate is installed; the entry's core remaining
  gap (no arm/profile selects `ContractGate` by default) is unchanged and stays open.

## Out of scope

- No change to which gate an arm installs by default (C0–C3 still install
  `AllowAllGate`/`ClaimGate` unless a contract path is explicitly given — unchanged
  experimental design).
- No causal-edges/relationship layer connecting a `POLICY_VERDICT` event to the
  tool-call event it responded to (`parent_id` stays `None`) — a separate, already
  backlogged item.
- No change to `ContractGate`'s own public interface (`check()`, `refusals()`,
  `shadow_refusals()`, `to_dict()`) — the runner reads its existing `.verdicts` list
  rather than `ContractGate` gaining any new responsibility.
- No other frontend copy audited beyond the one fabricated command found in
  `Agents.jsx` and the terminal chrome/cursor change — a full copy audit of every CLI
  example across the landing page is a larger task than this session's scope.

## Testing / verification

- `pytest tests/unit tests/integration -m "not slow"` — full suite must still pass,
  plus the new tests described above.
- Manual: run a task with a contract producing a refusal, then run `causalmesh verify`
  against the resulting chain directory and visually confirm a `POLICY_VERDICT` line
  appears verified.
- Frontend: `npm run build` after the `VerifyTerminal.jsx` chrome/cursor changes;
  visual check via headless browser screenshot (as done earlier this session) at
  desktop and mobile widths.
