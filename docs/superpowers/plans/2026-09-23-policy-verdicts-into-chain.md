# Policy Verdicts Into the Signed Chain, Plus Terminal Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every verdict the policy gate (`ContractGate`) reaches — refusal or
allow — a real, hash-linked, signed chain event under a genuine `policy_gate` signing
identity, closing the "Verdicts do not enter the signed chain" backlog item. Alongside
this, fix the hero terminal's window chrome/cursor and a fabricated CLI command found
during the same audit.

**Architecture:** One new `EventType.POLICY_VERDICT` member; a deterministically
derived `policy_gate` Ed25519 keypair registered with the relay whenever a contract is
in use; `runner.py` emits one event per accumulated `ContractGate.verdict` right before
building `RunResult`, using the existing `relay.ingest()` path — no new subsystem, no
change to `ContractGate`'s own interface. Frontend changes are independent and touch
only `VerifyTerminal.jsx` (visual) and `Agents.jsx` (one corrected command string).

**Tech Stack:** Python 3.13 (existing `causalmesh` package conventions), pytest;
React/Tailwind (existing landing-page component patterns).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/causalmesh/events/schema.py` | Add `EventType.POLICY_VERDICT` |
| `src/causalmesh/tasks/runner.py` | Derive `policy_gate` keypair; emit one chain event per verdict before returning `RunResult` |
| `tests/unit/test_event_schema.py` | Unit test: new event type round-trips through canonicalization |
| `tests/unit/test_policy_gate.py` | Unit test: `policy_gate` keypair derivation is deterministic and distinct from agent keys |
| `tests/integration/test_task_execution.py` | Integration test: a contract-driven run's verdicts appear as verified `POLICY_VERDICT` events on the chain |
| `docs/backlog.md` | Update two existing entries to reflect what's now resolved |
| `frontend/components/landing/VerifyTerminal.jsx` | Real macOS-style traffic-light buttons; smoother cursor |
| `frontend/components/landing/Agents.jsx` | Fix fabricated `causalmesh run` example to a real command |

---

## Task 1: `EventType.POLICY_VERDICT`

**Files:**
- Modify: `src/causalmesh/events/schema.py:47-65` (the `EventType` enum)
- Test: `tests/unit/test_event_schema.py`

- [ ] **Step 1: Read the existing test file to match its exact style**

Run: `sed -n '1,40p' tests/unit/test_event_schema.py` and confirm how existing
`EventType` members are tested (construction, canonicalization round-trip).

- [ ] **Step 2: Write the failing test**

Add this test to `tests/unit/test_event_schema.py` (place it in whichever existing
test class covers `EventType`, or add a new one if none does — match the file's
existing class-per-concept structure):

```python
class TestPolicyVerdictEventType:
    def test_policy_verdict_is_a_member(self) -> None:
        assert EventType.POLICY_VERDICT == "POLICY_VERDICT"

    def test_policy_verdict_round_trips_through_canonicalization(self) -> None:
        identity = EventIdentity(
            experiment_id="exp1",
            task_id="task1",
            run_id="run1",
            agent_id="policy_gate",
            arm="C3",
        )
        event = Event(
            event_id="run1_verdict_0",
            identity=identity,
            event_type=EventType.POLICY_VERDICT,
            sequence=0,
            timestamp_us=1_700_000_000_000_000,
            payload={"allowed": False, "reason": "test", "rule": "ownership"},
        )
        canonical = event.to_canonical_dict()
        assert canonical["event_type"] == "POLICY_VERDICT"
        # Re-canonicalizing the same structure must be byte-identical —
        # this is the property the whole hash chain depends on.
        assert event.canonical_bytes() == event.canonical_bytes()
```

Add `Event`, `EventIdentity`, `EventType` to the file's existing imports from
`causalmesh.events.schema` if not already imported (check first — the file likely
already imports all three, since it tests `Event` construction elsewhere).

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/unit/test_event_schema.py::TestPolicyVerdictEventType -v`
Expected: FAIL — `AttributeError: POLICY_VERDICT` (the member doesn't exist yet).

- [ ] **Step 4: Add the enum member**

In `src/causalmesh/events/schema.py`, find:

```python
class EventType(StrEnum):
    """The typed event vocabulary (spec §16).

    A StrEnum so the canonical form is the member's string value, giving
    stable bytes without any custom encoding.
    """

    INTENT = "INTENT"
    READ = "READ"
    WRITE = "WRITE"
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"
    TEST = "TEST"
    CLAIM = "CLAIM"
    RELEASE = "RELEASE"
    COMMIT = "COMMIT"
    FAILURE = "FAILURE"
```

Change the last line to add the new member:

```python
class EventType(StrEnum):
    """The typed event vocabulary (spec §16).

    A StrEnum so the canonical form is the member's string value, giving
    stable bytes without any custom encoding.
    """

    INTENT = "INTENT"
    READ = "READ"
    WRITE = "WRITE"
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"
    RENAME = "RENAME"
    TEST = "TEST"
    CLAIM = "CLAIM"
    RELEASE = "RELEASE"
    COMMIT = "COMMIT"
    FAILURE = "FAILURE"
    # Emitted by the policy plane (ContractGate), not by an agent, whenever
    # it reaches a verdict — allowed or refused. Signed under a dedicated
    # "policy_gate" identity (see tasks/runner.py) rather than an agent's
    # key, because a verdict is not an agent's action.
    POLICY_VERDICT = "POLICY_VERDICT"
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/unit/test_event_schema.py::TestPolicyVerdictEventType -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full unit suite for this file to confirm nothing else broke**

Run: `pytest tests/unit/test_event_schema.py -v`
Expected: PASS (all existing tests plus the 2 new ones)

- [ ] **Step 7: Commit**

```bash
git add src/causalmesh/events/schema.py tests/unit/test_event_schema.py
git commit -m "feat(events): add POLICY_VERDICT event type"
```

---

## Task 2: `policy_gate` signing identity

**Files:**
- Modify: `tests/unit/test_policy_gate.py`

This task only adds a test proving key derivation for the `"policy_gate"` actor id
works and is distinct from any agent's key — no source change yet, since
`KeyPair.derive` already accepts an arbitrary string and needs no modification. This
step exists to nail the identity's behavior down with a test *before* Task 3 wires it
into the runner, so a mistake in Task 3 is caught against a known-good expectation
rather than discovered only via the integration test.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_policy_gate.py` (near the top-level fixtures, or in a new
class — match the file's existing class-per-concept structure):

```python
from causalmesh.crypto.keys import KeyPair

...

class TestPolicyGateIdentity:
    """The signing identity a verdict event is attributed to.

    A verdict is reached by the policy plane, not by any agent in the run,
    so it needs its own signing identity rather than borrowing an agent's
    key — attributing it to an agent would misattribute provenance.
    """

    def test_policy_gate_key_is_deterministic(self) -> None:
        seed = b"causalmesh-test-seed-0000000001"
        a = KeyPair.derive(seed, "policy_gate")
        b = KeyPair.derive(seed, "policy_gate")
        assert a.public_key_hex() == b.public_key_hex()

    def test_policy_gate_key_differs_from_an_agent_key(self) -> None:
        seed = b"causalmesh-test-seed-0000000001"
        policy_key = KeyPair.derive(seed, "policy_gate")
        agent_key = KeyPair.derive(seed, "agent_a")
        assert policy_key.public_key_hex() != agent_key.public_key_hex()
```

Confirmed against `src/causalmesh/crypto/keys.py`: `KeyPair` exposes `public_key_hex()`
(a `str`) — used here instead of a nonexistent `public_key_bytes()`.

- [ ] **Step 2: Run the test to verify it fails only if the API differs**

Run: `pytest tests/unit/test_policy_gate.py::TestPolicyGateIdentity -v`
Expected: PASS immediately, since `KeyPair.derive` already exists and needs no new
code — this test documents and locks in existing behavior rather than driving new
implementation. If it fails, the failure will name the actual method signature
mismatch; fix the test (not the source) to match.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_policy_gate.py
git commit -m "test(policy_gate): lock in policy_gate key derivation as a distinct, deterministic identity"
```

---

## Task 3: Wire verdicts into the chain via `runner.py`

**Files:**
- Modify: `src/causalmesh/tasks/runner.py:179-203` (`_gate_for`), `:220-245` (keypairs
  and `Relay` construction), `:345-360` (before `RunResult` construction)
- Test: `tests/integration/test_task_execution.py`

This is the core change. `ContractGate.verdicts` already accumulates every verdict in
memory (confirmed reading `src/causalmesh/hooks/policy_gate.py` — no change needed
there). The runner needs to: (a) give the relay a `policy_gate` keypair whenever a
contract is in play, and (b) after the scenario finishes, turn each accumulated
verdict into a real `relay.ingest()` call.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/test_task_execution.py` (after the existing
`TestInformationContrast` class or wherever the file's other top-level test classes
end — run `grep -n "^class Test" tests/integration/test_task_execution.py` first to
see where to add it):

The task's real agent ids are needed to declare a contract owner. Run:
`grep -n "agent_id:" tasks/schema_handler_widen.yaml` — confirmed this returns
`agent_a` and `agent_b`, so `agent_a` (used below) is a real agent id for this task.

Also note: this file already has a `_key_ring(result)` helper (defined near the
bottom of the file, after `TestReproducibility`) that rebuilds a `PublicKeyRing` by
deriving a key for every distinct `agent_id` found in `result.records` — since the new
`POLICY_VERDICT` records will carry `agent_id: "policy_gate"`, this helper picks up
the policy identity automatically with no changes needed. Reuse it rather than writing
a new one.

```python
import yaml

from causalmesh.events.schema import EventType
from causalmesh.verifier import verify_chain


def _write_contract(tmp_path: Path, *, owner_of_config: str) -> Path:
    """A minimal contract that will produce both a refusal and an allow.

    `owner_of_config` owns src/handler.py; anyone else writing it is refused.
    Every other path is undeclared, so writes to it are allowed — giving the
    run at least one ALLOW verdict and, when the scenario has an agent that
    is not `owner_of_config` write to src/handler.py, at least one REFUSE.
    """
    contract_path = tmp_path / "causalmesh.yaml"
    contract_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "roles": [{"agent_id": owner_of_config, "owns": ["src/handler.py"]}],
                "policy": {"arm": "C3"},
            }
        ),
        encoding="utf-8",
    )
    return contract_path


class TestPolicyVerdictsOnTheChain:
    """A contract-driven run's verdicts become real, verifiable chain events.

    This is the property the backlog entry "Verdicts do not enter the
    signed chain" names directly: a refusal recorded only in the run
    artifact is not provable the way a chain event is. Running with a real
    contract and reading the resulting chain back is the only way to prove
    this rather than asserting it.
    """

    async def test_verdicts_appear_as_verified_policy_verdict_events(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        contract_path = _write_contract(tmp_path, owner_of_config="agent_a")

        result = await execute_task(
            task,
            RunConfig(
                experiment_id="exp_policy_verdicts",
                run_id="run_policy_verdicts",
                arm="C3",
                master_seed=SEED,
                contract_path=str(contract_path),
            ),
            workspace_root=tmp_path / "ws",
            fixtures_root=FIXTURES,
        )

        verdict_records = [
            r for r in result.records if r["event"]["event_type"] == "POLICY_VERDICT"
        ]
        assert verdict_records, "expected at least one POLICY_VERDICT event on the chain"

        # Every verdict-event is attributed to the policy_gate identity,
        # never to a participating agent.
        for record in verdict_records:
            assert record["event"]["identity"]["agent_id"] == "policy_gate"

        # Offline verification must accept the new event type with no
        # special-casing — proving this rather than asserting it is the
        # whole point of this test. `_key_ring` (already defined in this
        # file) picks up the policy_gate identity automatically because it
        # derives a key for every agent_id actually present in the records.
        report = verify_chain(result.records, _key_ring(result))
        assert report.valid, report.failures
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_task_execution.py::TestPolicyVerdictsOnTheChain -v`
Expected: FAIL with `assert verdict_records` raising `AssertionError: expected at
least one POLICY_VERDICT event on the chain` — the contract runs and produces a valid
chain, but nothing emits `POLICY_VERDICT` events yet, which is exactly the gap Steps 3
and 4 close.

- [ ] **Step 3: Add the `policy_gate` keypair to the relay**

In `src/causalmesh/tasks/runner.py`, find:

```python
    keypairs = {agent: KeyPair.derive(config.master_seed, agent) for agent in agent_ids}
```

Change to:

```python
    keypairs = {agent: KeyPair.derive(config.master_seed, agent) for agent in agent_ids}
    # The policy plane is not an agent, but its verdicts still need a real
    # signing identity so they can enter the chain — see docs/backlog.md's
    # "Verdicts do not enter the signed chain" entry. Only derived when a
    # contract is in play; an experiment run with no contract has no
    # ContractGate and therefore no verdicts to sign.
    if config.contract_path is not None:
        keypairs["policy_gate"] = KeyPair.derive(config.master_seed, "policy_gate")
```

- [ ] **Step 4: Emit one chain event per verdict before building `RunResult`**

In `src/causalmesh/tasks/runner.py`, find the comment and line just before
`RunResult(` is constructed:

```python
    exit_code = _run_integration_test(task, integrated)
    outcome = evaluate_outcome(task.success, workspace=integrated, test_exit_code=exit_code)

    result = RunResult(
```

Insert the verdict-emission block between the `outcome = ...` line and
`result = RunResult(`:

```python
    exit_code = _run_integration_test(task, integrated)
    outcome = evaluate_outcome(task.success, workspace=integrated, test_exit_code=exit_code)

    # Every verdict the policy gate reached becomes a real chain event —
    # not only refusals, so an unenforced arm's shadow-refusals (the
    # counterfactual §-referenced throughout policy_gate.py) are provable
    # too. `hasattr` rather than isinstance: the arms' own gates
    # (AllowAllGate, ClaimGate) have no `.verdicts` list to read, and that
    # absence is the honest signal that no contract was in play.
    if hasattr(gate, "verdicts"):
        policy_identity = EventIdentity(
            experiment_id=config.experiment_id,
            task_id=task.task_id,
            run_id=config.run_id,
            agent_id="policy_gate",
            arm=config.arm,
        )
        for index, verdict in enumerate(gate.verdicts):
            ingested = relay.ingest(
                event_id=f"{config.run_id}_verdict_{index}",
                agent_id="policy_gate",
                event_type=EventType.POLICY_VERDICT,
                identity=policy_identity,
                timestamp_us=utc_now_micros(),
                payload=verdict.to_dict(),
            )
            if not ingested.accepted:
                # A verdict that cannot be recorded is exactly the silent
                # gap this change exists to close — fail loudly rather
                # than returning a result that looks complete but is
                # missing evidence.
                raise RuntimeError(
                    f"policy verdict {index} could not be recorded on the "
                    f"chain: {ingested.reason}"
                )

    result = RunResult(
```

- [ ] **Step 5: Add the two new imports**

In `src/causalmesh/tasks/runner.py`, find:

```python
from ..crypto.keys import KeyPair
```

Change to:

```python
from ..crypto.keys import KeyPair
from ..events.schema import EventIdentity, EventType, utc_now_micros
```

- [ ] **Step 6: Run the integration test to verify it passes**

Run: `pytest tests/integration/test_task_execution.py::TestPolicyVerdictsOnTheChain -v -m "integration"`
Expected: PASS.

- [ ] **Step 7: Run the full integration suite to confirm nothing else broke**

Run: `pytest tests/integration -m "integration and not slow" -v`
Expected: PASS (existing tests unaffected — the change is additive and only activates
when `config.contract_path is not None`, which no other existing test sets).

Then run the slow suite too, since this specific test needs the `slow` marker (real
task execution):

Run: `pytest tests/integration/test_task_execution.py -v`
Expected: PASS (all tests in the file, including the pre-existing slow ones and the
new one).

- [ ] **Step 8: Commit**

```bash
git add src/causalmesh/tasks/runner.py tests/integration/test_task_execution.py
git commit -m "feat(runner): record every policy verdict as a signed chain event"
```

---

## Task 4: `docs/backlog.md` updates

**Files:**
- Modify: `docs/backlog.md:144-154` ("Verdicts do not enter the signed chain"),
  `docs/backlog.md:109-133` ("The gate is installable but not yet installed by
  default")

- [ ] **Step 1: Update "Verdicts do not enter the signed chain"**

Find in `docs/backlog.md`:

```
### Verdicts do not enter the signed chain

**Status:** `Verdict.to_dict()` is chain-shaped and tested, but no event type
is defined for it, so a refusal by the new gate is not yet evidence in the
§82 sense.

**Why this matters more than it looks:** the project's central claim is that
a refusal is recorded evidence rather than a log line. Until the verdict has
an event type, the policy plane's refusals are the one kind of refusal that
is not provable — which is precisely the property that distinguishes this
from a linter.
```

Replace with:

```
### Verdicts do not enter the signed chain

**Status: resolved.** `EventType.POLICY_VERDICT` exists
(`src/causalmesh/events/schema.py`), and `execute_task` now emits one chain event per
verdict `ContractGate` reaches — allowed and refused alike, so an unenforced arm's
shadow-refusals are provable too, not only the refusals that actually blocked a call.
Events are signed under a dedicated `policy_gate` identity, derived the same way every
agent's key is (`KeyPair.derive(seed, "policy_gate")`), because a verdict is reached by
the policy plane, not by any agent — attributing it to an agent's key would misattribute
provenance. `tests/integration/test_task_execution.py::TestPolicyVerdictsOnTheChain`
proves offline verification accepts the new event type with no special-casing, rather
than asserting it.

**What this does not change:** the arms' own default gates (`AllowAllGate`/
`ClaimGate`) are unaffected — verdict events are only emitted when a contract is in
play (`config.contract_path is not None`), which is exactly when `ContractGate` itself
is installed. See "The gate is installable but not yet installed by default" below for
the part of this story that is still open.
```

- [ ] **Step 2: Update "The gate is installable but not yet installed by default"**

Find in `docs/backlog.md`:

```
### The gate is installable but not yet installed by default

**Status (updated):** `ContractGate` in `hooks/policy_gate.py` satisfies the
same `Gate` protocol the arms already install, so the lifecycle boundary
takes it without a new code path. It is covered by 12 tests. What remains is
that no arm or profile selects it: a default run still installs `ClaimGate`.
```

Replace the **Status (updated):** paragraph with:

```
**Status (updated again):** `ContractGate` in `hooks/policy_gate.py` satisfies the
same `Gate` protocol the arms already install, so the lifecycle boundary takes it
without a new code path. It is covered by 12 tests, and — as of the change recorded
under "Verdicts do not enter the signed chain" above — every verdict it reaches now
becomes a signed chain event when it is installed. What remains is that no arm or
profile selects it: a default run still installs `ClaimGate`.
```

(Leave the rest of the entry — "Why the arms do not use it," "What it still blocks,"
"A bug this found in itself" — unchanged; only the Status paragraph needs updating.)

- [ ] **Step 3: Verify the file still reads coherently**

Run: `sed -n '109,175p' docs/backlog.md` and confirm both entries read correctly with
no leftover contradictions between the two (the second entry's "What it still blocks"
section should still make sense given the first entry's new resolved status).

- [ ] **Step 4: Commit**

```bash
git add docs/backlog.md
git commit -m "docs(backlog): record that policy verdicts now reach the signed chain"
```

---

## Task 5: `VerifyTerminal.jsx` — macOS-style window chrome and cursor

**Files:**
- Modify: `frontend/components/landing/VerifyTerminal.jsx`

- [ ] **Step 1: Read the current file to confirm exact current markup**

Run: `sed -n '145,180p' frontend/components/landing/VerifyTerminal.jsx` to see the
current three-dot header bar and cursor block, confirming line numbers before editing
(the file may have shifted slightly since this plan was written).

- [ ] **Step 2: Replace the three plain dots with traffic-light buttons**

Find:

```jsx
      <div className="flex items-center gap-2 border-b border-paper/10 px-4 py-3">
        <span className="h-2.5 w-2.5 rounded-full bg-paper/20" />
        <span className="h-2.5 w-2.5 rounded-full bg-paper/20" />
        <span className="h-2.5 w-2.5 rounded-full bg-marker" />
        <span className="ml-2 font-mono text-[10.5px] uppercase tracking-[0.12em] text-paper/45">
          causalmesh · verify
        </span>
```

Replace with:

```jsx
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
          causalmesh · verify
        </span>
```

Design notes for this change: the three buttons stay within this project's existing
`arm-c0`/`arm-c3`/`marker` palette (not macOS's literal red/yellow/green, which would
violate the single-accent-color discipline stated in `app/landing.css`) — close is
`arm-c0` (the same rust-orange already used for C0/refusal states elsewhere on the
page), minimize is `arm-c3`, maximize/active stays `marker`. Each shows a faint glyph
(×, –, ▲) only on hover of the group, matching how a real macOS window's traffic
lights reveal their glyphs on hover rather than showing them at rest. `aria-hidden`
because these are decorative (the terminal is not a real, controllable window) — this
matches `Section`'s own existing `aria-hidden` decorative-rule convention.

- [ ] **Step 3: Smooth the command-line cursor**

Find:

```jsx
          {(phase === "typing" || phase === "idle") && (
            <span
              aria-hidden="true"
              className="ml-0.5 inline-block h-[13px] w-[7px] translate-y-[2px] animate-pulse bg-marker align-middle"
            />
          )}
```

Replace with:

```jsx
          {(phase === "typing" || phase === "idle") && (
            <span
              aria-hidden="true"
              className="cm-terminal-cursor ml-0.5 inline-block h-[13px] w-[7px] translate-y-[2px] bg-marker align-middle"
            />
          )}
```

- [ ] **Step 4: Add the smoother cursor keyframe to `landing.css`**

Run: `grep -n "cm-mark-in\|@keyframes" frontend/app/landing.css | head -20` first, to
find an existing `@keyframes` block to place this near (match the file's existing
organization — keyframes appear to be grouped together based on earlier greps in this
session).

Add near the other keyframes in `frontend/app/landing.css`:

```css
/* A steadier, more deliberate blink than `animate-pulse`'s ease-in-out fade —
   a terminal cursor cuts on and off, it does not fade. Matches the timing
   the Palisade reference used for its own terminal cursor, translated into
   this project's own class naming rather than reusing its literal CSS. */
@keyframes cm-terminal-blink {
  0%, 45% { opacity: 1; }
  46%, 100% { opacity: 0; }
}

.cm-terminal-cursor {
  animation: cm-terminal-blink 1.05s steps(1) infinite;
}
```

- [ ] **Step 5: Build to confirm no errors**

Run: `cd frontend && npm run build`
Expected: succeeds with no errors.

- [ ] **Step 6: Visual check**

Run the dev server (`npm run dev` in `frontend/`, wait for
`curl -sf http://localhost:3000` to succeed), then use a headless browser (Playwright,
as used earlier in this session — see the scratchpad scripts already written this
session for the exact pattern) to screenshot the hero terminal at desktop width and
confirm:
- The three traffic-light circles render in the new colors (not plain grey dots).
- Hovering the group (simulate with Playwright's `hover()` on the button group) reveals
  the faint × / – / ▲ glyphs.
- The command-line cursor still blinks during the typing phase (visually distinguish
  from before is not required by an automated check — visually confirm no layout
  shift or broken rendering).
- No console errors.

Stop the dev server afterward (`lsof -ti:3000 -sTCP:LISTEN | xargs -r kill`).

- [ ] **Step 7: Commit**

```bash
git add frontend/components/landing/VerifyTerminal.jsx frontend/app/landing.css
git commit -m "feat(web): macOS-style traffic-light buttons and a steadier cursor blink in the hero terminal"
```

---

## Task 6: `Agents.jsx` — fix the fabricated `causalmesh run` command

**Files:**
- Modify: `frontend/components/landing/Agents.jsx:47-65` (`stepsFor` function)

- [ ] **Step 1: Confirm the current text**

Run: `sed -n '47,65p' frontend/components/landing/Agents.jsx`
Expected: confirms the third step still reads
`"causalmesh run --arm C3 --task schema_handler_widen"` (matching what this plan's
design doc found) before editing — if it has since changed, stop and re-check against
`causalmesh --help`/`causalmesh experiment run --help` for what the real command is
before proceeding, rather than assuming this plan's finding still holds.

- [ ] **Step 2: Replace the fabricated command**

Find:

```jsx
    [
      "Run under an arm",
      "causalmesh run --arm C3 --task schema_handler_widen",
      "The arm installs a channel and a gate. Nothing reads the arm name at runtime.",
    ],
```

Replace with:

```jsx
    [
      "Run under an arm",
      "causalmesh experiment run --profile smoke",
      "The profile selects the arm and task. Nothing reads the arm name at runtime.",
    ],
```

- [ ] **Step 3: Rebuild and confirm no other reference to `causalmesh run` remains**

Run: `cd frontend && npm run build`
Expected: succeeds.

Run: `grep -rn "causalmesh run\b" frontend/ --include="*.jsx" --include="*.tsx"`
Expected: no output (the fabricated command no longer appears anywhere in the
frontend).

- [ ] **Step 4: Commit**

```bash
git add frontend/components/landing/Agents.jsx
git commit -m "fix(web): replace a fabricated \`causalmesh run\` example with the real command"
```

---

## Task 7: Full verification pass

**Files:** none (verification only)

- [ ] **Step 1: Run the full Python test suite**

Run: `pytest tests/unit tests/integration -v -m "not slow"`
Expected: PASS, no regressions from the baseline (compare against the count from
before this plan's changes if in doubt — run `git stash` temporarily is NOT an option
mid-plan; instead just confirm 0 failed, 0 errored).

- [ ] **Step 2: Run the slow suite including the new integration test**

Run: `pytest tests/integration/test_task_execution.py -v`
Expected: PASS (includes the new `TestPolicyVerdictsOnTheChain` test).

- [ ] **Step 3: Run linters**

Run: `ruff check src/causalmesh/events src/causalmesh/tasks/runner.py tests/unit/test_event_schema.py tests/unit/test_policy_gate.py tests/integration/test_task_execution.py`
Expected: no findings. Fix any before proceeding.

- [ ] **Step 4: Confirm the frontend build is still clean**

Run: `cd frontend && npm run build`
Expected: succeeds.

- [ ] **Step 5: Manual end-to-end check**

Run a real task with a contract and verify the resulting chain from the CLI, matching
the design doc's manual-verification step:

```bash
mkdir -p /tmp/cm_verdict_check
cd /tmp/cm_verdict_check
causalmesh policy init
# edit causalmesh.yaml if needed, or use it as-is for a smoke check
```

(This step is exploratory/manual — if `causalmesh policy init`'s default output
doesn't produce a runnable end-to-end check easily from the CLI alone, it's acceptable
to rely on the automated integration test from Task 3 as the primary proof; note in
the final report whether this manual check was completed or whether the automated
test was relied upon instead.)

- [ ] **Step 6: Final review of all changed files**

Run: `git log --oneline -8` and `git diff main --stat`
Expected: a clean, reviewable sequence of 6 commits (event type, identity test, runner
wiring, backlog docs, terminal chrome, terminal command fix), each independently
buildable/testable.
