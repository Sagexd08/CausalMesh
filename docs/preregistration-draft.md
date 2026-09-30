# Preregistration draft: the 1920-run confirmatory collection

**Status: DRAFT, unsigned, not a preregistration.** Nothing in this file
commits the project to anything. The `confirmatory` profile stays
`gated=True`, and this document does not open the gate and does not run the
collection. It has two jobs:

1. State every design fact that the code already fixes, each with the file
   and symbol it comes from, so the eventual preregistration cites code and
   not memory.
2. List, as `TODO(owner)` items, every decision a human must make before the
   gate can honestly be opened. **No answer to any of them is proposed here.**
   Where `docs/PLAN.md` already names an intended method, it is quoted as
   "named in PLAN.md", which is a statement of intent to be ratified, not a
   decision on record.

Section numbers ("sec 38") refer to the specification the build has worked
from; that specification is not checked in (see `docs/backlog.md`,
"Staleness estimation"), so this draft can cite the code that implements a
section but not the section text.

Facts below were read from the tree at commit `feb891e` plus the branch this
file was written on. Re-derive them before signing; `pytest
tests/unit/test_preregistration_draft.py` checks the ones that are cheap to
check.

---

## 1. Design facts fixed by the code

### 1.1 Scale

| Fact | Value | Source |
|---|---|---|
| Profile name | `confirmatory` | `experiments/profiles.py`, `PROFILES["confirmatory"]` |
| Repetitions per (task, arm) cell | 120 | same, `repetitions=120` |
| Arms | `C0 C1 C2 C3` (all four) | `Profile.arms` defaults to `ARM_IDS` in `experiments/arms.py` |
| Task cap | none (`max_tasks=None`) | same |
| Gate | closed: `gated=True`; `profile("confirmatory")` raises unless `allow_gated=True` | `profiles.profile()`; CLI flag `--allow-gated` in `cli/commands_experiment.py` |
| Runs implied | `tasks x 4 x 120` | `Profile.run_count(task_count)` |
| The "1920" figure | `run_count(4) == 1920` | `tests/unit/test_experiments.py::test_the_confirmatory_profile_is_the_1920_run_design` |

**Discrepancy the owner must resolve (see TODO-TASKS).** 1920 assumes four
tasks. The repository at this commit does not contain four plannable tasks:

- `tasks/` holds three definitions: `schema_handler_widen` (family
  `schema_handler`), `concurrent_edit_collision` (family
  `concurrent_edit_collision`) and `cb_tinyrepo_task1` (family
  `cooperbench_import`).
- `_build_plan` in `cli/commands_experiment.py` deliberately drops every
  `COOPERBENCH_IMPORT` task, because an imported task's coordination shape is
  discovered and must pass its own sec 37 gate before joining a preregistered
  design (`docs/backlog.md`, "CooperBench import").
- So today `experiment plan --profile confirmatory --allow-gated` would plan
  `2 x 4 x 120 = 960` runs, not 1920. (`run_count(2) == 960`,
  `run_count(3) == 1440`, `run_count(4) == 1920`; computed from
  `Profile.run_count`, not by planning.)

The two eligible tasks differ in what enforcement can do, and the task files
say so:

- `schema_handler_widen`: ownership is disjoint, so C3 has nothing to block
  (`docs/PLAN.md`, Step 11).
- `concurrent_edit_collision`: `src/config.py` is genuinely contested; C3's
  refusal is expected to prevent the clobber and also block legitimate work.
  The header comment of `tasks/concurrent_edit_collision.yaml` calls that "a
  finding, not a defect".

### 1.2 Arms and factors

From `experiments/arms.py` (`ARMS`):

| Arm | Information | Enforcement |
|---|---|---|
| C0 | none (`NullChannel`, raises on any injection) | none |
| C1 | unbounded transcript | none |
| C2 | bounded structured metadata (window `w = 8` by default, `RunConfig.window`) | none |
| C3 | bounded structured metadata (same channel object as C2) | exclusive write claims |

### 1.3 Planned contrasts

From `experiments/arms.py` (`PRIMARY_CONTRASTS`); every difference is
`treatment - baseline` (`metrics/contrasts.py`, `ContrastResult`):

| Name | Baseline | Treatment | Isolates |
|---|---|---|---|
| `information_benefit` | C0 | C2 | information |
| `representation` | C1 | C2 | information representation |
| `enforcement_benefit` | C2 | C3 | enforcement |
| `complete_system` | C1 | C3 | representation and enforcement jointly (deliberately confounded) |

Code marks `complete_system` as "never evidence for either factor
separately". Whether any contrast is "primary" in the inferential sense is a
TODO below; the constant is named `PRIMARY_CONTRASTS` but no inferential
procedure consumes it.

### 1.4 Outcome definition (sec 38)

- `tasks/outcome.py`, `evaluate_outcome` returns a `TaskOutcome` whose
  `succeeded = tests_passed AND divergence_absent`.
  - `tests_passed` is `test_exit_code == 0` for the task's
    `success.integration_test` command, run once on the integrated workspace
    (`tasks/runner.py`, `_run_integration_test`).
  - `divergence_absent` is false if the task's `divergence_file` is missing or
    unresolvable, or contains its `divergence_marker`. A task with no divergence
    check configured records `no_divergence_check_configured` and is judged on
    tests alone.
- There is no subjective field anywhere in the outcome (`SuccessCriteria`
  in `tasks/definition.py`).
- `decide_acceptance` maps `succeeded` to `ACCEPT` / `REJECT`; `HUMAN_REVIEW`
  is declared but unreachable.
- The evidence (`exit_code`, `evidence` strings, `divergence_found_in`) is
  retained in the artifact under `outcome`. The actor id is at
  `event.identity.agent_id` and run success is `result.outcome.succeeded`
  (AGENTS.md, "Field names that are easy to get wrong").
- **An absent outcome is `unknown`, not a failure.** `metrics/accounting.py`,
  `RunMetrics.succeeded` is `None` when the artifact carries no outcome;
  `ArmMetrics.success_rate` divides by runs with a known outcome and is `None`
  for an empty denominator; `unknown_outcomes` is reported.

### 1.5 Design, ordering and seeds

From `experiments/randomization.py`:

- **Fully crossed.** Every task under every arm, `repetitions` times
  (`plan_experiment`). There is no random allocation to arms. `RunPlan.is_balanced`
  checks that every (task, arm) cell has the same count.
- **Order randomized as one flat sequence** (not within blocks), by
  `shuffled(items, master_seed, "plan/<experiment_id>")`: a Fisher-Yates
  shuffle whose index stream is a counter-mode SHA-256 of an HMAC-SHA256
  derived key. No `random`, no clock, no `os.urandom`.
- **Run ids are derived**, `<experiment_id>__<task_id>__<arm>__r<NNNN>`, so a
  replan reproduces them and a resumed collection recognises finished runs.
- **Per-run seed** is `derive_run_seed(master_seed, run_id)`
  (`scheduler/loop.py` passes it into `RunConfig.master_seed`).
- **Master seed.** The CLI accepts `--seed` (at most 32 bytes, padded with
  NULs; `_seed_bytes`). The default is the string
  `causalmesh-default-collection-01` (`DEFAULT_SEED`). Anyone holding the
  master seed can forge any actor's signatures (`docs/security.md`), so
  disclosure of the seed is itself a decision (TODO-SEED).
- `RunPlan.content_hash()` digests the plan including order, and
  `RunPlan.task_hashes` carries each task's `content_hash()`. These are the
  natural values to record in a preregistration; they cannot be filled until
  the task set and seed are chosen.

### 1.6 What executes in each run

- `tasks/runner.py`, `execute_task` builds every arm the same way, differing
  only in delivery policy, gate and channel.
- **The agents are `MockAgent`s**, hard-coded: `execute_task` constructs
  `MockAgent` with `model_id="mock"`, `model_version="1"`. A model-backed
  `ModelAgent` exists in `adapters/model_agent.py` and is exercised by its own
  tests, but `execute_task` does not use it.
- **The mock agent is deterministic and consumes no randomness.**
  `agents/mock.py` states "given the same script, the same seed and the same
  delivered events, the agent takes exactly the same actions", and a search of
  `src/causalmesh/agents/` finds no use of `identity.seed` in behaviour (the
  seed is recorded on the identity and drives key derivation only). Consequence
  to be checked empirically, not assumed: the 120 repetitions of one
  (task, arm) cell may be replicates of an identical run, in which case the
  effective sample size is the number of cells, not the number of runs, and a
  run-level test would overstate the evidence enormously (TODO-MOCK-VS-REAL,
  TODO-POWER).
- Runs are executed **sequentially by design** (`docs/scheduler.md`,
  "Sequential by choice"). Execution is resumable
  (`ExperimentRunner.prepare` / `run`).
- A **failed run is evidence** (sec 81): the loop catches `BaseException`,
  writes an artifact with the traceback, and the run stays in the denominator
  (`docs/scheduler.md`).

### 1.7 What analysis exists

| Piece | State | Source |
|---|---|---|
| Per-arm and per-task cost and success aggregation | built, descriptive, labelled PILOT | `metrics/accounting.py`, `cli/commands_analyze.py` |
| The four contrast differences (success delta, bytes delta, bytes ratio) | built, descriptive, labelled DERIVED | `metrics/contrasts.py` (`measure`) |
| Multi-rater kappa coding (sec 53) | built; operator-supplied judgements only | `analysis/agreement.py` |
| Inferential model, correction, intervals, equivalence, power analysis | **not built** | `docs/PLAN.md`, Step 13 "not built"; no code found |
| Report generator and figure labelling (sec 68) | **not built** | `docs/PLAN.md`, Step 14 |
| Staleness estimators | **not built**, definitions absent | `docs/backlog.md`; `docs/staleness-estimators-needed.md` |

`metrics/contrasts.py` says of itself: "These are descriptive differences, not
inferential results." So a preregistration that names an inferential analysis
is naming something that does not yet exist as code. The pooled enforcement
contrast is documented as misleading on this design (`docs/PLAN.md`, Step 11:
"the mean of 0.00 and -1.00 describes neither task"); `causalmesh analyze`
therefore pools only behind `--pooled`.

### 1.8 Named in PLAN.md, not decided

`docs/PLAN.md`, Step 13 describes the intended statistics as: "a preregistered
mixed-effects logistic model with task random intercepts, the four primary
contrasts, Holm-Bonferroni correction, 95% confidence intervals, TOST at +/-10
percentage points (a non-significant difference is explicitly *not* an
equivalence result), and configurable power analysis that states its
assumptions". `experiments/randomization.py` refers to "the mixed-effects
model in sec 48". These are quoted as the project's stated intent. Each is
re-listed below as something the owner must confirm or change. With only two
or three tasks, a task random intercept is a statistical question in its own
right (TODO-MODEL).

### 1.9 What the collection would freeze

To be recorded at signing, none of which exist yet: the git commit and a clean
working tree (`provenance.Environment.capture`, which flags a dirty tree as
"not attributable to a commit"); the task definitions' content hashes; the
`RunPlan.content_hash()`; the master seed policy; the configuration freeze hash
written by `causalmesh manifest write`. Manifests are tracked in git and
`data/raw/` is not (`docs/PLAN.md`, Step 14).

---

## 2. Decisions a human must make

Every item is `TODO(owner)`. No default is suggested. "Constraint from code"
lines say what the code already forces or forbids, not what to choose.

### TODO-HYPOTHESES

`TODO(owner):` State each hypothesis: which contrast, which outcome
(success proportion, coordination bytes, tokens, denials, something else), and
which direction, or two-sided.

- Constraint from code: one contrast per hypothesis is well defined by
  `PRIMARY_CONTRASTS`; `complete_system` is confounded by construction.
- Constraint from the tasks: on `concurrent_edit_collision`, C3 is expected
  to be able to lower success by blocking a legitimate second writer, so a
  one-sided "enforcement helps" hypothesis conflicts with that task's own
  header comment.

### TODO-PRIMARY

`TODO(owner):` Name the primary contrast(s) and the primary outcome. Decide
whether `representation`, `information_benefit`, `enforcement_benefit` and
`complete_system` are each primary, secondary or exploratory, and whether the
primary comparison is pooled across tasks or per task (the code's own
recommendation is per task; pooling is opt-in behind `--pooled`).

### TODO-ALPHA

`TODO(owner):` The significance level (alpha), the confidence level for
intervals, and whether tests are one- or two-sided. PLAN.md names 95% intervals
(see 1.8); confirm or replace.

### TODO-MODEL

`TODO(owner):` The statistical model and unit of analysis. PLAN.md names a
mixed-effects logistic model with task random intercepts (see 1.8). Decide
whether that is the model, given the number of tasks that will really be in the
design and the mock-agent determinism caveat in 1.6; what the unit of analysis
is (run, cell, task); and how repeated identical runs, if any, are treated. This
model must also be implemented and tested before it can be cited as a
preregistered analysis.

### TODO-MULTIPLICITY

`TODO(owner):` The multiple-comparison procedure and its family: which
hypotheses are corrected together. PLAN.md names Holm-Bonferroni (see 1.8);
confirm or replace, and say whether the family is all four contrasts, only the
primary ones, or per task.

### TODO-EQUIVALENCE

`TODO(owner):` Whether any hypothesis is an equivalence claim, and the margin.
PLAN.md names TOST at +/-10 percentage points (see 1.8). Code and sec 50
already require that a non-significant difference is not reported as
equivalence.

### TODO-TASKS

`TODO(owner):` The exact task set. The 1920-run figure needs four tasks; two
are plannable today (1.1). Decide which tasks make up the design, and whether an
imported CooperBench task may join once it passes its own sec 37 gate
(`tasks/validation.py`, the coordination-sensitivity gate, run under C0 and C2).
If the set stays at two or three tasks, the run count and the "1920" name change
and the preregistration must say so.

### TODO-REPS-AND-POWER

`TODO(owner):` The repetition count and its justification. 120 per cell is what
the profile carries; its derivation is not recorded anywhere in the repository.
`pilot` (3 repetitions) is described as the source of parameter estimates for
the power analysis (sec 76), "stored separately from the reference assumptions",
but no power-analysis code exists. Decide the target effect size and power, and
whether the pilot is run first.

### TODO-MOCK-VS-REAL

`TODO(owner):` Whether the confirmatory collection uses the deterministic mock
agent or real models.

- If **mock**: decide whether repetitions are meaningful at all (1.6), and
  what population the result is a claim about. `AGENTS.md` already says "Do not
  claim anything about agent behaviour. Every run so far used a deterministic
  mock agent." A mock-only collection measures the substrate, not agent
  behaviour, and the preregistration must be worded to match.
- If **real model(s)**: which model, version, provider and endpoint; sampling
  temperature; whether a per-run seed is passed (`adapters/model_agent.py`
  records endpoint, model, temperature, seed and token counts); prompt and tool
  set; who pays; and a code change, because `execute_task` currently
  constructs only `MockAgent`. That change is not a decision and has not been
  made.

### TODO-STOPPING

`TODO(owner):` Stopping rules. Fixed sample (run all planned runs) or any
interim look; what happens on a sustained failure rate or an infrastructure
fault; whether `--limit` partial executions may be analysed; who may stop and on
what evidence. Constraint from code: the scheduler is resumable and a failed
run stays in the denominator, so "stop early" and "drop failures" are choices,
not defaults.

### TODO-EXCLUSIONS

`TODO(owner):` Exclusion rules, stated before any data. At minimum decide: runs
whose outcome is `unknown`; runs that errored before the outcome was evaluated;
runs on a dirty working tree or a mismatched task hash; runs with a
`transport_failure` or `protocol_failure` if real models are used. Constraint
from code: the metrics layer counts an absent outcome as `unknown` and excludes
it from the success-rate denominator while reporting the count; a rule that
instead counts it as failure or drops it is a departure and must be declared.

### TODO-COMPUTE

`TODO(owner):` The compute budget: wall time, machines, and (for real models)
money. No per-run timing figure is recorded in the repository, and runs are
sequential by design, so wall time is `runs x seconds-per-run` and
seconds-per-run is unmeasured. If spend is involved, the ledger and gate in
`policy/` can enforce a ceiling; the amount is the owner's.

### TODO-SEED

`TODO(owner):` The master seed: chosen how, kept where, published when. The
default string in the CLI is a placeholder, not a decision. Because the seed
can forge signatures, publish it only after the collection is verified, or state
why not.

### TODO-DEVIATIONS-AND-REGISTRY

`TODO(owner):` Where and when the preregistration is deposited and
timestamped; who signs it; how deviations are recorded; the analysis-code freeze
point (a commit); and which results will be labelled CONFIRMATORY versus
EXPLORATORY under sec 67/68 (the report generator that would apply the labels
is not built).

---

## 3. What opening the gate would still require

1. Every TODO above answered in writing, in a signed version of this file.
2. The task set reconciled with the run count (TODO-TASKS).
3. The inferential analysis implemented and tested (1.7), or the
   preregistration scoped to what exists.
4. If real models: the runner change (TODO-MOCK-VS-REAL).
5. A clean working tree and recorded hashes (1.9).
6. A typed `--allow-gated` by a human, which the code deliberately leaves in
   shell history.

None of these is done here. `profile("confirmatory")` still raises.
