# The experiment loop

Spec §39 to §42 and §79 to §81. The scheduler turns single runs into a
collection: it plans what to run, fixes the order, executes each unit, and
records what happened — resumably, and without ever losing or duplicating a
run.

Status: describes Step 10 of `docs/PLAN.md`. The smoke profile has been
executed for real against `schema_handler_widen`; the pilot machinery
exists and the confirmatory profile is gated (§77).

## What the scheduler is not allowed to do

Most of the design is negative. A scheduler is unusually dangerous to an
experiment because its failures are *silent*: a collection that quietly
dropped a run still produces a clean-looking dataset, just with a smaller
denominator and no record of the gap.

| Refusal | Why |
|---|---|
| Never skip a run silently | A missing run shrinks the denominator invisibly |
| Never retry a failure | Re-running until it passes is selection on the outcome |
| Never overwrite an artifact | Raw evidence is immutable (§31) |
| Never re-execute a finished run | Two results for one planned unit inflates *n* |
| Never resume a changed plan | Pools runs from two different designs |

Each is a test, not a convention:
`test_a_failed_run_is_not_retried`,
`test_an_existing_artifact_is_never_overwritten`,
`test_a_completed_run_cannot_restart`,
`test_a_changed_plan_under_the_same_id_is_refused`.

## The design is data, not branches

`experiments/arms.py` declares the four arms as a frozen table of two
factors. Nothing branches on an arm id there; the objects that *implement*
an arm are installed elsewhere (delivery policy in the relay, gate in the
hooks, channel in the runner). Keeping the description separate from the
construction means the analysis layer can read the design without importing
the runtime, which §5 forbids.

The payoff is that the factor structure is checkable:

```
test_c2_and_c3_differ_only_in_enforcement
test_c1_and_c2_differ_only_in_information
test_the_single_factor_contrasts_really_vary_one_factor
```

The last one is the important one. Each contrast declares which factor it
isolates, and the test confirms that the two arms named actually differ in
exactly one factor. A future edit to an arm cannot quietly invalidate a
contrast's interpretation without failing.

`complete_system` (C1 vs C3) deliberately varies both factors. That is
recorded in the contrast's own rationale and asserted by
`test_the_complete_system_contrast_is_declared_confounded`, so it can be
reported as an end-to-end effect and never as evidence for either factor
alone.

## Randomization: derived, never sampled

The design is fully crossed — every task under every arm, the same number
of times — so there is no allocation to randomize. Randomization exists
solely to protect against **order** effects (§41). If arms ran in blocks,
C0 would occupy the cold start of every collection and its results would be
confounded with machine state.

Every draw comes from `HMAC-SHA256(master_seed, label)`. No
`random.random()`, no clock, no `os.urandom`.

Two decisions worth stating:

**Not `random.Random(seed).shuffle`.** That is deterministic only for one
CPython version — the Mersenne Twister seeding and the shuffle algorithm
are implementation details with no cross-version guarantee. §84 requires
reproducibility across machines and versions, not merely across two runs on
one laptop.

**HMAC rather than `sha256(seed + label)`.** Concatenation is ambiguous
when either part varies in length, so two different `(seed, label)` pairs
could produce the same input bytes. HMAC's padding removes the ambiguity.

Plan draws and run-seed draws are namespaced separately, checked by
`test_run_seeds_do_not_collide_with_plan_draws`. Not a threat this project
models — but a run's signing key being predictable from its schedule
position is exactly the kind of coincidence that is hard to notice later.

Rejection sampling gives a uniform index rather than a modulus, whose bias
would be tiny but undocumented.

### What the tests actually check

A shuffle is easy to test vacuously. These try harder:

| Test | Bug it catches |
|---|---|
| `test_it_is_a_permutation` | Elements lost or duplicated |
| `test_it_actually_reorders` | An identity "shuffle" that passes everything else |
| `test_the_distribution_is_not_obviously_degenerate` | An index stream that collapses |
| `test_the_order_is_randomized_not_blocked` | Arms running in blocks |
| `test_task_order_does_not_affect_the_plan` | Filesystem listing order leaking in |

The distribution test is not a uniformity proof — that needs a statistical
test this suite has no business running. It checks that every element
reaches many positions across seeds, which catches the realistic failure.

## Run ids are derived, not generated

```
{experiment_id}__{task_id}__{arm}__r{repetition:04d}
```

Resume depends entirely on this. A UUID would make every replan a fresh set
of runs and defeat resume completely
(`test_replanning_gives_identical_run_ids`).

## The state machine (§63)

```
PLANNED ─→ RUNNING ─→ COMPLETED
              │  ├───→ FAILED
              │  ├───→ TIMED_OUT
              │  └───→ ABANDONED
              └─→ (crash) ─→ ABANDONED ─→ RUNNING   (resume)
```

**COMPLETED does not mean the task succeeded.** It means the run reached
its end and produced a verdict. A run whose agents failed the task is
COMPLETED with `succeeded=False`, and it belongs in the denominator.
Conflating execution status with task outcome would turn the primary
outcome into a survivorship rate
(`test_completed_and_succeeded_are_independent`).

**ABANDONED is not terminal, and that is the whole point.** An interrupted
run has no verdict, so re-executing it is not selection on the outcome —
unlike re-executing a FAILED run, which is. The two must stay
distinguishable or a resume could quietly re-run failures until they
passed.

`succeeded` is nullable and stays nullable: a harness crash leaves no
verdict, and `None` must not become `False`, which would report a task
failure nobody observed (`test_unknown_success_stays_distinct_from_failure`).

## Claiming is atomic, and this was verified by breaking it

`claim_next` does its SELECT and UPDATE inside one `BEGIN IMMEDIATE`
transaction. Without it, two workers both read PLANNED and both execute the
same run.

`test_claiming_is_atomic_under_concurrency` runs six real threads against a
real file-backed database. To confirm it is not passing vacuously, the
transaction was replaced with a plain read followed by a separate write:
**the test failed with 19 claims for 12 runs.** The guarantee is enforced by
SQLite, not by luck.

The same mutation discipline was applied to two other guarantees:

- Forcing every run to execute as C0 while the index recorded the planned
  arm — a perfectly balanced, entirely wrong dataset — fails
  `test_the_arms_separate_as_the_task_predicts`.
- Corrupting one event before export fails
  `test_every_chain_verifies_offline_from_its_artifact` with a chain break,
  an invalid signature and a key mismatch.

## Evidence is written before the index is updated

The order is deliberate. If the process dies between the two steps, the run
is found RUNNING at next startup, marked ABANDONED, and re-executed — which
costs time but cannot lose evidence. The reverse order could mark a run
COMPLETED whose artifact was never written.

A run left RUNNING by a killed process would otherwise be stranded forever,
since `claim_next` skips that state, and the collection could never
complete. `test_a_crashed_run_is_recovered_and_re_executed` leaves a run
RUNNING exactly as a kill would, then opens a fresh runner — a new process,
in effect — and requires it to finish.

## A failed run is evidence (§81)

The loop catches `BaseException`, not `Exception`. A `KeyboardInterrupt`
still records the run before propagating; otherwise an operator's Ctrl-C
strands a run in RUNNING with no evidence of why.

Every failure writes an artifact containing the full traceback, so the
failure is diagnosable rather than reduced to a class name
(`test_a_failed_run_still_writes_an_artifact`). Four tests cover the
failure path, including `test_a_failure_leaves_no_run_stranded`.

## Profiles, and the closed gate

| Profile | Repetitions | Notes |
|---|---|---|
| `smoke` | 1 | One task. Answers "does it run", estimates nothing |
| `pilot` | 3 | Parameter estimates for the power analysis (§76) |
| `small` | 10 | Exploratory |
| `medium` | 30 | Substantial, still not preregistered |
| `confirmatory` | 120 | The 1920-run design — **gated** |

The confirmatory profile raises unless `allow_gated=True` is passed
explicitly. Building the machinery and running it are different acts: the
machinery must exist and be tested, but executing 1920 runs commits to a
preregistered analysis, and this project has not preregistered one.

The flag is a typed argument the CLI surfaces, not an environment variable
or a config key — those can be set by a file nobody read, while a typed
flag leaves the decision in the shell history. The gate's message explains
*why*, not merely that (`test_the_gate_reason_explains_itself`).

## Sequential by choice

Runs share this machine. A parallel scheduler would make wall-clock timings
depend on what else happened to be running, which is a confound in the
coordination-cost measurement (§44) — and that is one of the outcomes, not
a diagnostic. Parallelism needs per-run resource isolation before it can be
honest, and is tracked in `docs/backlog.md`.

## The index is operational, not evidential

`data/raw/<experiment>/index.db` records which runs exist and what state
each reached. It is mutable by design, because a run's *state* legitimately
changes as it progresses.

That does not conflict with §31. The evidence is the signed chain and the
run artifacts; nothing in the index feeds a reported number, so mutating it
cannot alter a result. What it can do is prevent a result from being
produced twice.

Every state change is retained in a `transitions` table. Without it, a run
abandoned and resumed twice looks identical in `runs` to one that ran
straight through (`test_the_resume_is_visible_in_the_transition_log`).

`counts()` returns every state including the zeroes, so "no failures" and
"failures not counted" cannot look the same.

## Executed for real

The smoke profile, run against the repository (`experiment_id=smoke_step10`,
4 runs, 27.4s wall clock). Execution order was **C3, C1, C2, C0** — not
blocked, as §41 requires.

| Arm | Chain verifies | Succeeded | Coordination bytes | Injected | Unique turn digests | Claims |
|---|---|---|---|---|---|---|
| C0 | ✓ | ✗ | **0** | 0 | **1** | 0 |
| C1 | ✓ | ✓ | 361 | 11 | 4 | 0 |
| C2 | ✓ | ✓ | 196 | 3 | 4 | 0 |
| C3 | ✓ | ✓ | 196 | 3 | 4 | **2** |

Read against the manual-inspection checklist in `docs/PLAN.md`:

1. **Chains link and verify offline.** All four verified from the persisted
   JSON, with keys rebuilt from each run's derived seed — what an external
   auditor would have to do, not what the relay says about itself.
2. **C0 received zero coordination bytes.** Zero bytes, zero injections,
   and `received_no_coordination` true for every agent.
3. **C0's context never changed.** One unique turn digest across all eight
   turns — the empty-context digest, repeated. The informed arms have four
   distinct digests each. This is §14's proof rather than an assertion: it
   is a property of what entered the context, not of what the code intended.
4. **C2 and C3 spend identically** (196 bytes), as they must, since they
   differ by enforcement alone.
5. **C3 alone holds claims** (2, one per owned path), with no denials —
   each agent wrote only what it owned on this task.

C1 costs 84% more than C2 for the same outcome, which is the
representational difference the C1→C2 contrast is designed to measure. One
run per cell estimates nothing; it is reported here as evidence the
machinery works, not as a result.

## An inspection bug worth recording

The first pass of the artifact inspection read a key that does not exist
(`context_digests`; the real field is `turn_digests`) and reported
`digests=0` for **every** arm. That looked like it confirmed C0's isolation
while actually confirming nothing — the C0 claim is only meaningful if the
informed arms differ, and a uniform zero makes the check vacuous.

The error was in the throwaway inspection script rather than in the
codebase, and no test depended on it. It is recorded because it is the
exact shape of a false confirmation: a check that returns the expected
value for the wrong reason. The corrected reading is what the table above
reports.
