# Fragment: SDK claims and a human checkpoint handler (for the integrator)

Not a permanent doc. Contents to merge into `CHANGELOG.md` and
`docs/backlog.md`, which this track did not edit. It closes two bullets under
"Developer SDK (Phase 1)" / "What does not ship" (Human-in-the-loop approval
from the SDK; Claims) and the last paragraph of "Checkpoints and identity,
from parsed-and-ignored to real" ("What this does not do").

## Summary

**Claims in the SDK.** `CausalMesh(claims=ClaimRegistry(...))` (and
`from_config(..., claims=...)`) hands the registry to `ContractGate.build`.
That is the whole of enforcement: `Gate._rule_claim` already asks
`registry.may_write` and `ContractGate.check` already calls `record_denial`
on a `claim` refusal. There is no second gate and no claim logic in the SDK.
The lease run id and the gate run id are both `mesh.run_id`, so a lease
protects exactly what the gate consults (`"sdk"` by default).

Leases are taken explicitly: `mesh.claim(agent_id=, path=, duration_us=,
now_us=)` returns the registry's `ClaimOutcome` as data (granted, or refused
with the `holder`), `mesh.release(claim_id=, ...)` likewise, `mesh.denials()`
reads the registry's denials for this run, and `mesh.claim_registry` exposes
the registry. `path` may also be a `Resource`. The lease key is
`Resource.path(path).identity` (for example `path:src/a.py`), so
`src\a.py`, `./src/../src/a.py` and `src/a.py` are one lease.

**Choice stated: no acquire-on-first-mutating-call.** It was considered and
not built, for three reasons. (1) A contested implicit acquire would write a
denial in `acquire` and the gate would write another for the same blocked
attempt; the enforcement count would be doubled, which is the class of defect
`record_denial`'s docstring records. (2) An implicit lease is never released
unless something says when, so the first agent to touch a path would lock it
out until expiry without anyone having decided that. (3) It needs the
resolved paths before the gate runs, which means reaching into
`ToolGateway.execute`, a file other work is editing. A lease is a statement
an agent or operator makes; making it explicit keeps it that.

**Unchanged:** default is off (`claims=None`, the gate built with
`registry=None`, behaviour identical to before). `ContractGate.build` keeps
the registry for its own refusal recording only when enforcing, but passes it
to the policy gate always, so on C0-C2 the claim rule still runs as a shadow
check: a contested call executes and the result carries `would_refuse`,
`shadow_rule="claim"` and `shadow_reason`; the signed event records
`would_refuse`. No denial row is written on an unenforced arm, because
nothing was blocked. (A contested `mesh.claim()` is an exception on any arm:
`ClaimRegistry.acquire` writes its own denial, as it always has.)

**Human checkpoint handler.** `TerminalCheckpointHandler`
(`src/causalmesh/policy/terminal_handler.py`, exported from
`causalmesh.policy`) satisfies the existing `CheckpointHandler` protocol, so
the gate is unchanged. It refuses on every failure and approves only on an
explicit `y`/`yes`:

- injectable `input_stream` / `output_stream` (defaults: `sys.stdin`,
  `sys.stderr`, so `--json` stdout is not mixed with prompts);
- `require_tty=True` refuses without asking when input is not a terminal;
- end of input, a closed or raising stream, an unwritable output, and a
  timeout (`timeout_s`, default 120, per checkpoint) all refuse. Reading
  happens on a daemon thread so the caller waits with a deadline;
- a line typed after its question timed out is discarded, never taken as the
  answer to the next question;
- unintelligible answers are re-asked `max_attempts` (default 3) times, then
  refused;
- output is printable ASCII. Control characters, ANSI escapes, newlines and
  non-ASCII in agent-controlled names (resource, agent id) are shown as
  `\xNN` / `\uNNNN`, backslash doubles, long values are truncated with their
  length stated;
- a lock serializes prompts across threads;
- `decisions()` is its own log (agent, resource, checkpoint, approved, reason,
  outcome of `answered|eof|timeout|no_tty|no_output|invalid`, `now_us` as
  passed to the gate). It is outside the signed chain.

`CausalMesh(checkpoint_handler=...)` and `from_config(checkpoint_handler=...)`
forward a handler to `ContractGate.build`. CLI: `causalmesh experiment run
--checkpoint-prompt` installs the handler only when a contract was found, the
contract declares `policy.checkpoints`, and stdin is an interactive terminal;
otherwise it says so on stderr and `AutoDenyHandler` stays. The scheduler now
keeps a handler object out of the run artifact's `provenance` (it is not
data; its class name is recorded instead), sets `reproducible: false` when the
handler declares `deterministic = False`, and adds a `checkpoint_decisions`
list (the handler's log for that run) to the artifact envelope. A run without
a handler serializes exactly as before.

**A defect found on the way.** `policy.checkpoints: [{on: path, ...}]`
written in a YAML file did not load: YAML 1.1 reads an unquoted `on` as the
boolean `True`, so the entry arrived as `{True: "path"}` and the parser raised
a `TypeError` (from sorting the unknown key names) instead of a
`ContractError`. No test loaded a checkpoint from YAML. `_parse_checkpoint`
now reads the `True` key as `on`, and `_reject_unknown` no longer assumes
string keys. Pinned in `tests/sdk/test_checkpoints.py`.

## What the chain records (unchanged, stated)

- Runner (`tasks/runner.py`): CHECKPOINT_DECIDED is written only for
  checkpoint verdicts that refused, under the `checkpoint` identity, whose key
  is derived only when `contract.checkpoints` is non-empty.
- SDK: a refused checkpoint is the call's FAILURE event, with `rule:
  "checkpoint"` and the handler's reason in the payload. No CHECKPOINT_DECIDED
  event.
- Approved checkpoints leave no chain record in either path. The SDK's WRITE
  event for an approved call says nothing of the approval. Pinned by a test
  so a change is deliberate.

## CHANGELOG bullets

Added:

- `CausalMesh(claims=ClaimRegistry)`: exclusive leases apply to SDK sessions.
  `mesh.claim()`, `mesh.release()`, `mesh.denials()`, `mesh.claim_registry`.
  Off by default. Same run id for lease and gate.
- `TerminalCheckpointHandler`, a human-attached `CheckpointHandler` (timeout,
  bounded re-prompts, refuse on EOF/closed/no-tty, ASCII-escaped prompts,
  serialized prompts, own decision log).
- `CausalMesh(checkpoint_handler=...)`; `causalmesh experiment run
  --checkpoint-prompt`.
- Run artifacts from a run with a checkpoint handler record the handler's
  class under `provenance`, `reproducible: false` for a non-deterministic one,
  and `checkpoint_decisions`.

Fixed:

- `on: path` (unquoted) under `policy.checkpoints` in `causalmesh.yaml` no
  longer raises a `TypeError` while loading.

## backlog.md edits to make

Replace these two bullets under "Developer SDK (Phase 1) / What does not
ship":

- Human-in-the-loop approval from the SDK: **built** (handler forwarded;
  `TerminalCheckpointHandler`). Remaining gaps listed below.
- Claims: **built, opt-in.** `claims=` and explicit `mesh.claim()`.

Replace the final paragraph of "Checkpoints and identity" ("What this does not
do") with: a terminal-facing handler and `--checkpoint-prompt` now exist; the
gaps below are what is still not built.

**Not built, recorded with reasons:**

- **Acquire-on-first-mutating-call.** See the choice above. If wanted, the
  safe form is an explicit `auto_claim_us=` on `CausalMesh` that acquires in
  `ToolGateway.execute` before the gate and skips `record_denial` for a
  refusal its own acquire already wrote.
- **Approved checkpoints are not on the chain, in either path.** A person's
  yes is the thing an auditor would most want to see signed, and it is the one
  decision not recorded. Recording it means a `checkpoint` key in the SDK
  relay (derived only when checkpoints are declared, as the runner does), a
  reservation of that agent id so `execute(agent_id="checkpoint")` cannot
  forge the identity (`mesh.agents` would otherwise list it as a callable
  agent), and a decision on whether the runner records approvals too. The
  reason text must stay free of clock and host to be reproducible, which the
  terminal handler's is. Not cheap enough to do beside a change to
  `ToolGateway`, so not done; the SDK's refusal record is the FAILURE event
  described above, not a CHECKPOINT_DECIDED event. Runner and SDK therefore
  still differ here.
- **`checkpoint_decisions` is an envelope, not evidence.** The handler's own
  log is outside the signature, so it can be edited after the fact. The
  signed record of a refusal is the chain's; of an approval, there is none.
- **Checkpoints are consulted on every arm.** `Gate.check` runs checkpoints
  whether or not it enforces, so `--checkpoint-prompt` asks a person on C0-C2
  too, where a "no" only becomes `would_refuse`. The CLI says so when it
  installs the handler. A scripted or arm-aware handler is the way around it;
  the handler does not know the arm.
- **The prompt blocks the calling thread.** The protocol is synchronous. From
  `execute_async` it blocks the event loop until the person answers or
  `timeout_s` passes, and concurrent agents wait in line behind the lock.
  The timeout is per checkpoint and counted from when the question is shown.
- **A daemon reader thread can be left blocked on stdin** after a timeout.
  It reads at most one line and that line is discarded. CPython can print a
  "could not acquire lock ... at interpreter shutdown" message if the process
  exits while a daemon thread is inside a blocking stdin read; not observed
  in the tests, which use injected streams, and not exercised against a real
  terminal in this environment.
- **Real terminals were not driven.** `require_tty`, Windows consoles and a
  live TTY were tested only with injected streams. The output is ASCII on
  purpose so cp1252 cannot raise; that has not been run on Windows.
- **A run that uses the handler is not reproducible from the seed.** It says
  so (`reproducible: false`); the answers are a person's.
- **Claim expiry uses the caller's clock.** `mesh.claim()` defaults `now_us`
  to the wall clock. A caller who passes synthetic `now_us` to `execute()`
  must pass the same clock to `claim()`, or a lease is judged against two
  clocks. Leases are not in the signed chain (the registry is outside it), so
  this does not touch chain reproducibility. The default claim id is
  `<run_id>_<agent_id>_<n>` from a per-session counter: two sessions sharing
  a registry and a run id can collide (`ClaimError`); give them different run
  ids or pass `claim_id=`.
- **The runner seeds leases with raw paths, so `ContractGate`'s claim rule
  does not see them (verified, not fixed).** `tasks/runner.py` acquires
  `task.role_for(agent).owns` entries as written (`src/a.py`), while
  `ContractGate` asks `may_write` with `Resource.path(...).identity`
  (`path:src/a.py`). A registry holding `src/a.py` answers `granted=True` to
  `may_write(path="path:src/a.py")` for a second agent and `False` for
  `may_write(path="src/a.py")`. So in a contract-gated experiment run the
  `claim` rule never fires on those leases (ownership and the other rules
  still do), while the narrow `ClaimGate` the arms install without a contract
  keys on the raw path and does. The SDK does not have this problem because
  `mesh.claim()` leases on the identity. Not changed here: it alters what a
  contract-gated C3 run measures, and the fix (acquire on `identity`, or make
  the registry normalize kind-prefixed and bare paths to one key) is a
  decision for whoever owns the experiment arms.

## Tests

- `tests/sdk/test_claims.py`: off by default; two agents on one path (holder
  allowed, other denied, one recorded denial, result fields, FAILURE event);
  C0-C2 report `would_refuse` and run with no denial; lease and gate share
  the run id (custom and default, cross-run isolation); outcomes as data
  (contested, renew, release, release by non-holder, expiry, unusable path);
  misuse raises. Mutation-checked: `registry=None` in `_build_runtime` fails
  13 of them.
- `tests/sdk/test_checkpoints.py`: default refusal, forwarded handlers, the
  terminal handler through the SDK, what the chain records (including the
  approved-leaves-nothing gap), unenforced arm, YAML `on`.
- `tests/unit/test_terminal_checkpoint.py`: answers, every refusal path,
  timeout and the stale-line rule (mutation-checked), concurrency, log.
- `tests/adversarial/test_terminal_checkpoint_escape.py` (adversarial): ANSI,
  CR, forged lines, backspace, bidi override, emoji, NUL, huge names.
- `tests/integration/test_checkpoint_prompt.py`: the CLI flag only acts on an
  interactive stdin; a real smoke collection with the handler writes a
  serializable artifact, `reproducible: false`, per-run decisions that sum to
  the handler's log, and CHECKPOINT_DECIDED on the C3 chain.

Nothing here says anything about agent behaviour. The contended-path tests
use scripted calls, and the checkpoint tests use scripted answers.
