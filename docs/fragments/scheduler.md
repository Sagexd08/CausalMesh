<!--
Fragment for docs/backlog.md, written by the scheduler slice. Not folded yet:
the two entries below replace "Timeout as a distinct run state (Step 10)" and
"Agent handoff package on recovery" in place, and the CHANGELOG line at the
bottom goes under Unreleased.
-->

### Timeout as a distinct run state (Step 10)

**Status: built, cooperative only.** `ExperimentRunner(run_timeout_s=...)` runs each
run under a whole-run watchdog (`_Watchdog` in `src/causalmesh/scheduler/loop.py`).
When the budget lapses the run's task is cancelled, the agent loop in `execute_task`
catches the cancellation, seals the chain it has (verdicts, then an acceptance decision,
all at the fixed post-run simulated time) and returns a `RunResult` with
`interrupted=True`. The scheduler records the run `TIMED_OUT`. It is opt-in: the default
is no budget, so an unconfigured collection behaves and reproduces exactly as before.
`causalmesh experiment run --run-timeout SECONDS` sets it; `--run-timeout 0` and
negative values are refused rather than timing out every run.

What a timed-out run leaves behind:

- **Partial evidence, kept.** The artifact carries the partial chain whole, and it
  verifies offline like any other. Partial workspace digests are kept too.
- **Outcome unknown, not failed.** The index records `succeeded=None`, and the artifact
  withdraws `result.outcome` (so every reader that looks for `outcome.succeeded` sees
  unknown) and keeps the half-finished workspace's score under `result.partial_outcome`.
  Counting a timeout as a task failure would claim a measurement nobody made.
- **Never accepted, and the chain says so.** The signed `ACCEPTANCE_DECIDED` event is
  `REJECT` with `run_interrupted_before_completion` in its evidence, via
  `decide_acceptance(outcome, interrupted=True)`. The default rule is unchanged.
- **Never retried.** `TIMED_OUT` stays terminal and non-retryable;
  `test_a_timed_out_run_is_never_retried` runs it through a real resume.
- **No wall-clock value in the signed chain.** Budget, elapsed time and grace are in
  `envelope.watchdog` on the artifact, outside the signature; a test asserts every
  event timestamp sits inside the simulated clock's range. The artifact is marked
  `reproducible: false`, because where the cut lands depends on timing in general
  (with a mock agent that hangs at a fixed turn it is deterministic, and a test
  compares two timed-out runs' chains).

**What this does not do:**

- **Cooperative cancellation only.** Cancellation lands where an agent `await`s. A run
  wedged in a blocking call (a synchronous `subprocess.run`, a C extension, a model
  client with no async timeout) blocks the event loop itself, so the watchdog cannot
  fire at all. The integration check after the agents (`_run_integration_test`, up to
  300 s, synchronous) is in the same position. Closing this needs the run to execute off
  the loop (a worker thread cannot be killed either, so realistically a subprocess per
  run), which also belongs with the per-run resource isolation the parallel-execution
  entry already needs.
- **A run that swallows cancellation is abandoned, not killed.** After the grace period
  (`timeout_grace_s`, default 30 s) the scheduler records `TIMED_OUT` with no chain
  (the artifact says `evidence: none: ...` and carries no `chain` key, so it reads as
  "no evidence" and not as "an empty run") and moves on. The orphaned task keeps running
  in the process. Tested with a deliberately stubborn agent.
- **The harness's own cancellation is still recorded as FAILED.** Pre-existing:
  `_execute_one` catches `BaseException`, so a cancelled collection (Ctrl-C reaches it
  as `CancelledError`) records the in-flight run `FAILED` ("harness raised") rather than
  leaving it `RUNNING` for the next startup to abandon and resume. Not changed here
  because it alters behaviour with no budget configured.
- **One budget for every run.** No per-task or per-arm budgets, and the budget is not in
  the plan hash, so a resume may use a different one. That is deliberate for now (a
  timeout is an operational limit, not a factor) but it means two collections of the
  same plan are not guaranteed the same set of runs reaching `COMPLETED`.
- **Command-level timeouts are unchanged.** They still live in the tool layer (§22) and
  still surface as `CommandResult.timed_out`.

### Agent handoff package on recovery

**Status: prerequisites built; nothing uses them.** The two things the entry said
had to exist first now do, and nothing else does.

- **A scheduler state.** `RunState.HANDED_OFF` ("run continues under a different
  agent"), additive in `scheduler/states.py`. Legal transitions: `RUNNING -> HANDED_OFF`,
  and out of it to `RUNNING` (the continuation) or `ABANDONED`. It is not terminal and
  not retryable (a cold re-run would discard the work being handed over). `RunIndex` gains
  `hand_off()` and `continue_handed_off()` so the state is writeable through the same
  transition-checked path as the rest, and `abandon_running()` now also sweeps
  `HANDED_OFF` at startup (a run waiting for a continuation that only a live process
  could start is stranded in a single-process loop), recording the state it actually
  found in the transition log.
- **A record shape.** `HandoffPackage` in `scheduler/handoff.py`: run and task identity
  (`task_hash` pins the task's content), `from_agent` and `to_agent`, a single
  `repository_digest`, the `diff` so far, `test_results`, `prior_decisions` (by chain
  event id), frozen, with `to_dict`/`from_dict` and canonical `to_json`/`digest`.
  `diff` and `test_results` are `None` when not computed and `()` when computed and
  empty; `to_agent` is `None` until a recovery decision picks one; a test result's
  `exit_code` and `passed` can be unknown. No timestamp, host or absolute path can
  enter it (paths are validated repository-relative), so the same handoff serialises
  to the same bytes and could later be committed to by hash without touching a
  bit-reproducible chain.

**Persisted-schema implications.** None that need a migration. `runs.state` and
`transitions.to_state` are free `TEXT` with no `CHECK`, `counts()` iterates
`RunState.ALL` so the new state shows up as a zero, and a database written before the
state existed reads unchanged (tested). The one direction that does not work is the
reverse: an older build reading a database that contains `handed_off` rejects the row
in `check_transition` (unknown state). That cannot happen yet, since nothing assigns
the state, and it is the reason the addition should ship before the code that assigns it.
`tui/monitor.py` knows the state (styled, counted as in-flight).

**What it would still take** (none of this is built):

- A **producer**: something that builds a `HandoffPackage` from a live run. The
  repository digest and diff need a defined baseline (the fixture at run start) and the
  workspace digests `execute_task` already computes are the raw material, but the
  single `repository_digest` is not computed anywhere, so its definition (which files,
  how ordered) is still open. Test results have two candidate sources (the agent's own
  `TEST` events and the harness's integration check) and which one a handoff carries is
  undecided.
- A **chain event** for the handoff (a new `EventType`, which is a schema change to
  `events/` and `docs/protocol.md`), signed by an identity that is neither agent's nor
  `policy_gate`'s, committing to the package by `digest()`. Until then a handoff would be
  an unsigned fact about a signed chain.
- A **consumer**: a second agent that is actually given the package, which is the
  multi-agent orchestration this entry has always been waiting on. The loop still runs
  exactly one agent per run and never assigns `HANDED_OFF`.
- The **`recover` decision** (retry the same agent, switch agents, escalate) that would
  assign it, which is where the Jev adapter becomes useful.
- A decision on what `attempts` means across a handoff. `continue_handed_off()` leaves it
  alone (a continuation is not another attempt), which is a choice nothing has yet tested
  against a real use.

### CHANGELOG (Unreleased)

- Scheduler: opt-in whole-run watchdog (`--run-timeout`); runs that exceed it reach
  `TIMED_OUT` with partial evidence preserved and a verifiable chain.
- Scheduler: `RunState.HANDED_OFF` and the `HandoffPackage` record shape, as prerequisites
  for agent handoff on recovery. Not wired into the loop.
