### Causal edges over the chain (fragment: replaces "What it would take (remaining)")

**Status: both remaining items built.** The acceptance decision now has a real edge
to the evidence it was decided from, and `causalmesh analyze --edges` reads edges
back out of run artifacts. `EdgeIndex` stays in-process; the CLI reads artifacts, not
an index.

**The integration test result is now a chain event.** `execute_task` already ran the
task's integration test (`_run_integration_test`, the harness measuring the result,
outside the agents' tool boundary) and fed its exit code to `evaluate_outcome`. It now
also records it as `EventType.INTEGRATION_TEST_RESULT`, under a dedicated
`integration_test` identity (key derived from the master seed, like `acceptance` and
`policy_gate`), immediately before `ACCEPTANCE_DECIDED`. It is a new type rather than
a reuse of `EventType.TEST`: `TEST` is an agent running tests in its own workspace,
and the two must stay distinguishable on the chain.

**Why this does not compromise reproducibility.** Timestamp is `post_run_time_us`
(`base_time_us + max_turns * tick_us`), the same deterministic instant the verdict and
acceptance events use; no wall clock. The payload is exactly
`{command, exit_code, ran}`: the task's fixed command and the exit code. Stdout,
stderr, duration and the integrated workspace path are deliberately absent, because
`pytest -q` prints elapsed time and the workspace lives under a temp directory. A test
that never ran (timeout or `OSError`) is `exit_code: null, ran: false`, not a 0. The
exit code was already inside the chain as `integration_test_exit_code=N` in the
acceptance evidence, so this adds no new source of variation, only a second place
the same value is signed. `TestDeterminism::test_two_runs_of_the_same_arm_agree`
still passes, and `TestAcceptanceEdge` pins the exact payload key set, that two runs
produce identical `chain_hash` and `signature` for the new event, that a chain holding
it verifies offline after a round trip through a JSONL file against a key ring
rebuilt from the seed, and that editing the recorded exit code breaks verification.

**The edge, and what it claims.** `acceptance -> integration test`, `REQUIRED`, one
per run, appended to `RunResult.edges` after the denial edges. It is `REQUIRED`, not
`CAUSED`, on purpose: `decide_acceptance` is a function of `outcome.succeeded`, which
is `tests_passed AND divergence_absent`, and the divergence-marker check reads the
integrated workspace and is not a chain event. The test result is a necessary input,
not the sole cause, and the edge's `note` says so. Both endpoints exist on the chain
(`TestAcceptanceEdge::test_every_edge_endpoint_is_a_real_chain_event`).

**Side effect to know about.** Every run's chain gains one event, so `head_hash`
values recorded before this change no longer match a re-run. Two runs of the same
arm agree with each other, which is what the determinism test checks; a stored
pre-change hash is a statement about the old chain. `run.json` artifacts from before
this change verify as they always did.

**`causalmesh analyze --edges`.** Follows the existing command's conventions: `--json`
is the machine path, tables carry a label (per-edge rows `[PILOT]`, counts by kind
`[DERIVED]`), the JSON payload carries `"label": "PILOT"`, descriptive only. It shows:

- counts by relationship kind, every kind listed so a real zero reads differently
  from a missing kind;
- per edge, both event ids and a label resolved against the artifact's own `chain`
  (e.g. `FAILURE by agent_b, denied`, `ACCEPTANCE_DECIDED by acceptance, ACCEPT`,
  `INTEGRATION_TEST_RESULT by integration_test, exit code 0`). An id the chain does
  not contain reads `unresolved`; an artifact with no chain reads `unknown`;
- `unknown`, not 0, for a run whose artifact has no `result.edges` key. This changed
  a shipped behaviour: `edges_for_run` used to read a missing key as an empty tuple,
  which the old CLI then summed into `total_edges: 0`, the confident zero AGENTS.md
  forbids. `RunEdges.recorded` now separates "recorded none" from "predates edges";
  `total_edges` and `by_relationship` are `null` when nothing counted was recorded
  and otherwise count only the runs that recorded, with `runs_edges_unknown` beside
  them. Per-run JSON has `edges: null`, not `[]`, for an older run.

Labels are ASCII (non-ASCII payload text is backslash-escaped) and Rich escapes them
so a `[tag]` in a payload is not read as markup.

**What it would still take:**

- *More population sources.* Two relationships are populated. `Event.parent_id` is
  still rejected as a source (see above). `Event.references` is still unused by any
  production call site. `CAUSED`, `RECOVERED` and `SUPERSEDED` have no writer at all:
  `RECOVERED` needs the handoff record from "Agent handoff package on recovery", and
  `SUPERSEDED` needs a call site that knows one event replaces another, which no
  current one does. The divergence check is the acceptance decision's other input; it
  could become a chain event the same way the test did, which would let the edge
  become two edges, but it is a workspace inspection with no natural exit code and
  that was not attempted.
- *The positional denial pairing is untouched.* It still raises if the verdict and
  denied-event counts disagree.
- *The analyze surface reads artifacts, not `EdgeStore`.* Edges recorded by a caller
  through `EdgeStore` rather than by `execute_task` are not visible to it.
- *Label resolution is by id, for the four event types it knows how to describe.* Any
  other event type gets `TYPE by actor` with no detail, which is accurate but terse.
- *No `--edges` filter by kind or run.* The table lists everything; `--json` plus
  `jq` is the filter today.
- *Platform runs.* Checked on Linux only; per `scripts/check.py`, Windows and macOS
  each need their own run.
