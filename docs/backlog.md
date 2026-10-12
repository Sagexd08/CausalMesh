# Backlog

Everything this build does **not** do, recorded as a tracked item rather
than left as a silent gap. `docs/PLAN.md` commits to this: where an
implementation falls short, the documentation says so plainly.

An entry here is a deliberate scope decision with a stated reason. It is
not a to-do list of things forgotten.

## Declared non-goals for the vertical slice

These are the five items `docs/PLAN.md` names explicitly.

### Real LLM adapters (OpenAI, Anthropic, local)

**Status (Phase 1): built and tested; no hosted model executed.**

`OpenAIClient`, `AnthropicClient` and `LocalClient` exist, written against
the chat-completions wire protocol rather than vendor SDKs, and are tested
over real HTTP against a server that implements both protocols. Every
coordination guarantee holds with a model driving — see `docs/adapters.md`.

**What remains untested:** whether a real hosted model follows the action
protocol reliably enough to complete a task, and at what
protocol-failure rate. That needs an API key and a budget, and spending
money is the operator's decision. `LocalClient` was also not exercised
against a live local server: Ollama, vLLM and LM Studio were all probed and
none was running on this machine.

**Why it was deferred until Phase 1:** building the substrate against a
deterministic agent means a failing test is unambiguous. With a
nondeterministic model in the loop from the start, every failure is "the
harness is broken" *or* "the model did something different today", and a
coordination substrate cannot be debugged through that fog.

**What it still blocks:** every claim about *agent behaviour*. This build
measures the platform, not language models. Nothing in it supports a claim
about how real coding agents coordinate.

**A note on determinism (§84):** a run with a hosted model is not
bit-reproducible, and `ModelSettings` does not pretend otherwise.
Temperature 0 is not a reproducibility guarantee on any hosted provider —
batching, aliased model updates and GPU floating-point non-associativity
all produce variation. The settings remove the randomness that can be
removed and record the rest. The chain remains verifiable: it records what
happened, which is a different property from being able to repeat it.

### CooperBench import (§54)

**Status: the loader has been run over the real CooperBench dataset. All 30
tasks, 199 features and 652 feature pairs import with 0 failures. The real
§37 gate was run on 3 pairs and returned NOT SENSITIVE for all 3, by the
same winner-take-all merge mechanism the synthetic example showed. A
content-level merge now exists as an opt-in (2026-10-03, "Content-level merge
for contested paths" below): with it a scripted replay solves 142 of the 652
pairs, and the three pairs above separate into three different, explained
outcomes. Nothing
about any agent's behaviour is claimed: every run used deterministic mock
agents replaying the dataset's own gold patches.** (Earlier status: proven on
one synthetic worked example only, because no network was available then.)

**Why it was deferred until now:** the task system (§35–38) had to exist
and be proven on a task whose coordination structure is known by
construction before importing tasks whose structure has to be discovered.
`schema_handler_widen` was built so the §37 gate could be validated against
a task where the expected answer was known.

**What is built.** `causalmesh.tasks.cooperbench` (`import_task`,
`import_dataset`) reads a CooperBench-shaped
`dataset/<repo>/task<id>/feature{1,2}/{feature.md,feature.patch,tests.patch}`
directory and produces a `TaskDefinition`, mapping `feature1` -> `agent_a`
and `feature2` -> `agent_b` — CooperBench's own two-feature structure
matches this project's two-agent floor directly. Two design decisions,
recorded in the module's own docstring rather than only here:

- **Patches are materialized at import time, not applied at run time.**
  `agents/script.py`'s `Action` DSL has no diff-applying action kind, only
  literal `write`/`create` content. Adding one (`ActionKind.PATCH`) was
  considered and rejected: it would mean shelling out to `git apply` while
  a scripted run is in flight, making what actually lands in a workspace
  depend on the machine's `git` version rather than solely on the YAML —
  exactly the "task that could execute arbitrary-ish operations" risk
  `tasks/definition.py`'s own module docstring argues against. Instead the
  loader applies each feature's `feature.patch` once, at import time,
  against the supplied base-repo state, and bakes the resulting literal
  content into ordinary `write` actions. The shipped task YAML stays pure
  data with no runtime patch application, so §33's reproducibility
  property is untouched.
- **Contested paths are discovered, not assumed.** `touched_paths` parses
  unified-diff `--- a/`/`+++ b/` headers out of each feature's patch;
  `contested_paths` is the intersection of the two features' touched-path
  sets, and `AgentRole.owns` excludes any contested path from either
  role — this is exactly the "structure has to be discovered" property
  that distinguishes a CooperBench import from `schema_handler_widen`.

**A fifth `TaskFamily`, `COOPERBENCH_IMPORT`, was added** rather than
reusing one of the four §35 families. All four existing families name a
coordination shape chosen by the task's *author* in advance; a CooperBench
import's defining property is that its shape — contested or not, which
paths — is discovered from real patches, not declared. See
`TaskFamily`'s own docstring for the full argument.

**Divergence has no fabricated marker.** CooperBench's real success
criterion ("both patches merge cleanly AND pass tests") has no single
scalar the way `schema_handler_widen`'s `HANDLED_FIELDS` marker does.
`divergence_file`/`divergence_marker` are left `None` on an imported task
unless a caller supplies real ones by hand for a specific pair; an import
with no marker validates as a task with no divergence check, not a task
with an invented one. This is a genuine limitation of the import, not
patched over.

**The synthetic worked example (first proof, kept).** When the loader was first built no real CooperBench data was vendored and the sandbox had no network, so it was proven against a small, clearly-labelled SYNTHETIC sample at `tests/fixtures/cooperbench_sample/` (one fake repo, two tiny features, real `git diff` output against that fake repo). The full pipeline ran end to end from it: loader -> `tasks/cb_tinyrepo_task1.yaml` (checked in) -> `fixtures/cb_tinyrepo_task1/` (checked in) -> `validate_structure` (passes) -> `check_sensitivity`, the real §37 gate, executed for real. Its verdict was **NOT SENSITIVE**, C0 0/1 and C2 0/1, because both features add a different key to the same dict in `src/greeter.py` and `tasks/runner.py::_integrate_workspaces` resolves a contested path to a single last writer from the signed chain rather than merging both features' changes. `tests/integration/test_cooperbench_import.py::TestQualityGate` pins it. The loader description above (`feature1` and `feature2`) is that synthetic layout; the real layout differs, below.

**Run against the real dataset (recorded 2026-09-30; evidence in `docs/evidence/cooperbench-real-import.json` and `cooperbench-real-gate.json`, counts and statuses only, no repository contents).**

- `git clone --depth 1 https://github.com/cooperbench/CooperBench` succeeded from the implementer's environment (commit `63b9d44d9f39a02fccf5bf0052db48a917a011fd`, 14 MB), so the earlier "no network" limitation did not apply there.
- The loader's assumed layout was checked against the real `dataset/` tree. The shape `dataset/<repo>_task/task<id>/feature<N>/{feature.md,feature.patch,tests.patch}` is right, and all 199 feature directories have all three files. Four things the synthetic sample hid were wrong or missing, each fixed with tests:
  1. **A task is not two features.** 29 of the 30 tasks have 3 to 12 features (one has 2); the unit of work is a pair, 652 in all. The old loader read `feature1` and `feature2` and ignored the rest, so it could reach 30 of 652 pairs (4.6%) and would have said nothing about the other 622. `import_task(features=(i, j))`, `feature_numbers`, `feature_pairs` and `import_dataset(pairs="all")` now cover every pair.
  2. **The base repository is not in the dataset.** Each task's `setup.sh` and `Dockerfile` name an upstream clone URL and a pinned `BASE_COMMIT`; nothing is vendored and nothing is a checkout. `cooperbench_base.parse_base_spec` reads those two facts (text only, `setup.sh` is never executed; one task builds its URL from variables, which it resolves and refuses if any stays unresolved). `base_files_for_paths` fetches only the files a pair's patches touch with a blobless shallow fetch of the one commit (44 MB for the 30 tasks in total), and `checkout_base_repo` writes a full tree when a run needs one. Network is needed the first time; a cache directory makes re-reads offline (tested).
  3. **Latent bugs, not hit by this data but real.** `touched_paths` read a removed line such as `-- a comment` (rendered `--- a comment`) as a file header; it now consumes hunks by their declared line counts, with a `---`/`+++`/`@@` look-ahead so a miscounted patch cannot swallow the next file. Text was read and written with universal-newline translation, which rewrites CRLF files; it now moves bytes. `git apply`'s throwaway repo no longer commits (one fewer hidden dependency on `user.name`). `touched_paths` agrees with `git apply --numstat` on all 199 `feature.patch` files.
  4. **The dataset's own `run_tests.sh` cannot be the integration test.** It is container-era: it installs dependencies from the network and takes patch paths as arguments. `ImportOptions(hidden_tests="pytest")` generates a harness instead (see the gate run).
- `import_dataset_report` imports every pair and records each failure with a stage (`base_repo`, `import`, `definition`, `unexpected`) and a reason, instead of raising on the first one or dropping it. `scripts/cooperbench_real.py import` runs it and writes the summary.

| Import result | |
|---|---|
| tasks attempted / with at least one imported pair | 30 / 30 |
| features | 199 |
| pairs attempted / imported / failed | 652 / 652 / 0 |
| pairs with at least one contested path (same file edited by both features) | 652 of 652 |
| contested paths per pair | 1 path: 512 pairs, 2: 128, 3: 12 |
| pairs whose gold patches conflict under `git merge` (CooperBench's own `gold_conflict_report.json`) | 499 |
| pairs whose gold patches `git merge` cleanly | 153 |
| pairs that `validate_structure` (§36) passes, fixture check skipped | 652 of 652 |

Every pair's `feature.patch` applied cleanly to the real base files, so there is no import failure to explain. Zero failures is a real result and not a filter: nothing was skipped and the report lists every pair. The 153 clean-merge pairs are worth reading next to the gate result: this platform calls them contested too, because it contests by file, not by hunk.

**The real §37 gate, on 3 pairs.** Pair `(feature1, feature2)` of three tasks, fixed before any verdict was seen and chosen because they are pure-Python repositories whose tests run with almost no dependencies: click `task2800`, jinja `task1621`, dirty-equals `task43`. Each fixture is the whole upstream tree at the pinned commit (not committed, not vendored). The hidden-test harness is this loader's own, so it was validated before its verdicts were used, against CooperBench's two stated properties: for all three tasks every feature's tests FAIL on the untouched base and PASS with `combined.patch` applied. The fidelity of the materialised write actions was also checked byte for byte against `git apply` on the full checkout (9 actions, 0 differences; a one-off check, not committed).

| Task | Contested path | Gate verdict, as produced |
|---|---|---|
| click `task2800` f1,f2 | `src/click/core.py` | NOT SENSITIVE, C0 0/1, C2 0/1 |
| jinja `task1621` f1,f2 | `src/jinja2/loaders.py` | NOT SENSITIVE, C0 0/1, C2 0/1 |
| dirty-equals `task43` f1,f2 | `dirty_equals/__init__.py`, `dirty_equals/_other.py` | NOT SENSITIVE, C0 0/1, C2 0/1 |

Diagnostic, not the verdict: in each arm's integrated workspace one feature's tests pass and the other's fail, identically under C0 and C2 (click: feature1 passes, feature2 fails; jinja and dirty-equals: feature1 fails, feature2 passes). That is the synthetic sample's mechanism: `_integrate_workspaces` resolves a contested path to a single last writer's whole file, so two features that both edit one file cannot both survive, whatever either agent was told. No verdict was tuned. Reproduce with `python scripts/cooperbench_real.py import|gate` (see the script; the gate needs `pytest`, `markupsafe` and `pytz` importable by `python`). Tests added: `tests/unit/test_cooperbench_real_layout.py` and `tests/integration/test_cooperbench_hidden_tests.py`; the earlier CooperBench tests pass unchanged.

**What this does not claim.**

- Nothing about agent behaviour. The mock agents replay gold patches.
- Nothing about the 649 pairs the gate was not run on. "Not sensitive" for 3 pairs is not a claim about CooperBench. The mechanism suggests any pair where both features edit one file is affected the same way, but that was not run.
- Not CooperBench's evaluation. CooperBench tests each agent's real patch, or the `git merge` of two, against per-feature tests; this platform integrates by file ownership and last writer. The generated harness also runs the Python test files each `tests.patch` touches, not the file list in the task's own `run_tests.sh`, so a pass here is not CooperBench's pass.
- Not a statement that the platform is wrong to be winner-take-all; only that it cannot express a same-file, different-hunk feature pair, which is the commonest shape here (512 of 652 pairs share exactly one file).
- The hidden tests are not hidden. `hidden_tests="pytest"` writes the `tests.patch` files into the fixture at `.cooperbench/`, so any future non-mock agent would see them. Fine for mock agents, not for real ones.
- Divergence still has no fabricated marker: an imported task validates as a task with no divergence check unless a caller supplies a real marker by hand.

**What it would still take.**

- The gate on the other Python pairs. It costs a full checkout and a working test environment per task; `dspy`, `llama_index` and `datasets` need heavy dependencies that were not installed. 24 of 30 tasks are Python; Go (3), JavaScript (2) and Rust (1) have no harness (import works for them, the gate does not).
- ~~A content-level merge for contested paths~~: built as an opt-in, see below. Making it the default is still a platform decision (it changes what "success" means for every task and invalidates comparison with every earlier result), so it was not made.
- Move hidden tests out of the workspace before any real agent runs.
- Pair selection for a real experiment (`subsets/lite.json` has 100 pairs); none was made.
- ~~One suite failure seen on Linux (`test_path_budget`, `File name too long`)~~: a test bug, fixed 2026-10-03. The test built a single 300-character path component, which exceeds `NAME_MAX` (255) on Linux, so the test's own `exists()` raised. The product's refusal was correct.

**Content-level merge for contested paths (built 2026-10-03, opt-in).**

`TaskDefinition.contested_merge` is `last_writer` (default, unchanged) or `three_way`. `three_way` merges the two agents' files against the fixture with `src/causalmesh/tasks/merge3.py`: a pure-Python diff3 over `difflib`, no dependency and no run-time dependence on the machine's `git` (the objection that rejected `ActionKind.PATCH` above). A region both sides changed differently, or touched adjacently, is a conflict (git's rule); it is recorded on `RunResult.merge_conflicts` (`None` when nothing was merged, which is not zero) and fails the run whatever the tests say. The field is serialised only when not the default, so no existing task's hash, YAML or evidence changed. `ImportOptions(contested_merge=...)`, `BatchOptions.contested_merge` and `--contested-merge` carry it. Tests: `tests/unit/test_merge3.py` (including a Hypothesis check against `git merge-file`), `tests/unit/test_contested_outcome.py`, `tests/integration/test_contested_merge.py` (the same two edits fail under `last_writer` and pass under `three_way`), and `TestThreeWayMerge` in `tests/integration/test_cooperbench_batch_run.py`.

*Validated against git, not trusted.* `python scripts/cooperbench_real.py merge-check` merges every contested file of all 652 real pairs with this code and with `git merge-file`, and compares the pair-level verdict with CooperBench's own `gold_conflict_report.json` (evidence: `docs/evidence/cooperbench-merge-check.json`, pair ids and counts only).

| Check, CooperBench `63b9d44` | Result |
|---|---|
| Contested files merged | 804 |
| File-level verdict agrees with `git merge-file` | 794 of 804 (98.8%) |
| Files both call clean whose merged bytes are identical | 173 of 174 |
| Pair-level verdict agrees with `git merge-file` | 642 of 652 (98.5%) |
| Pair-level verdict agrees with CooperBench's gold report | 636 of 652 (97.5%): 494 both conflict, 142 both clean, 11 we conflict and it is clean, 5 we are clean and it conflicts |
| Hypothesis fuzz against `git merge-file`, distinct lines | 0 disagreements in 400 generated cases per run (and 3000 in a one-off probe) |

The 10 file-level disagreements (5 stricter than git, 5 looser) were read, not averaged away. The one inspected (jinja `task1559` f3-f10) is two edits that meet at the boundary of a large rewrite: one side rewrites base lines 528-573 and the other inserts directly after line 573. The likely cause is that `difflib` and git's `xdiff` place the edge of that rewrite differently, so one sees the edits as adjacent and the other does not. That is inferred from the shape of the edits; the exact alignment was not traced, and the other nine were not inspected. It is consistent with the limitation `merge3.py`'s docstring states, and it is not a logic error in the general case (the distinct-line fuzz agrees completely). It is rare, but the five looser ones mean this merge can call something clean that git calls a conflict; the integration test, not the merge, is what decides whether the combination is right.

*What it does on the real pairs.* `scripts/import_cooperbench.py --contested-merge three_way` over all 652 pairs (evidence: `docs/evidence/cooperbench-batch-three-way.json`; 0 failed, 0 skipped, 83 s with 4 jobs): gold-patch replay solves **142 of 652 pairs (21.8%)** under the offline oracle, identically in C0 and C2 (the arms differ on 0 pairs, so the gate is NOT SENSITIVE for all 652, as it must be for agents that do not read the channel). Against CooperBench's git result: 137 solved and git-clean, 5 solved and git-conflicting, 16 unsolved and git-clean, 494 unsolved and git-conflicting. The 16 are the 11 where this merge is stricter than git, plus 5 that merge cleanly but fail the oracle because both features make an *identical* edit (click `task2800` f2-f6, f3-f6, f4-f6, f6-f7; jinja `task1559` f9-f10): a merge keeps one copy and the line-multiset oracle expects two. That is an oracle artifact, not a merge error.

*The three recorded pairs, re-run with the merge* (`docs/evidence/cooperbench-real-gate-three-way.json`; the `last_writer` re-run reproduced the recorded verdicts and per-feature results exactly, with the new preflight in place):

| Pair | Merge | Integrated workspace, real pytest harness | Reading |
|---|---|---|---|
| jinja `task1621` f1,f2 | clean | both features pass, C0 1/1 and C2 1/1 | the first real imported pair the platform solves; the dataset agrees it merges |
| click `task2800` f1,f2 | clean | feature 1 passes, feature 2 fails | a **semantic** conflict with no textual one: feature 1 makes `_resolve_context` close its context on exit, feature 2 adds an `on_exit` callback fired on close and a test that it must not fire during completion. Each passes alone (checked by running the harness in each agent's own workspace); the merge is correct (integrated `core.py` is base plus both edits, 4 + 37 = 41 changed lines) |
| dirty-equals `task43` f1,f2 | 2 files conflict | both fail | a textual conflict; the dataset's gold report also says conflict |

Winner-take-all had shown all three as one identical accident. The merge separates a pair it solves, a pair whose features are semantically incompatible, and a pair that conflicts textually, which is the distinction a coordination benchmark needs.

**What this does not claim.**

- Nothing about agent behaviour. Every run is a scripted replay of gold patches; the arms cannot differ, so no merge could make the gate SENSITIVE. A SENSITIVE verdict on an imported pair needs an agent whose behaviour depends on what the channel told it.
- Not CooperBench's evaluation. The oracle is offline line-multiset equality for the 652-pair run and a generated pytest harness for the 3; neither is CooperBench's own tests. 142 of 652 is "pairs this platform's replay-and-merge solves under that oracle", not a CooperBench score.
- The merge is line based and cannot detect semantic incompatibility (click above). It does not follow renames. It is not byte-identical to git on repeated-line files (the 10 files above).
- `three_way` applies only to paths declared `contested`. A path both agents change that the task did not declare is still taken by ownership.

**What it would still take.** The gate with pytest on the other 21 Python tasks (heavy per-task environments: `dspy`, `llama_index`, `datasets`); a harness for Go (3), JavaScript (2) and Rust (1); moving hidden tests out of the workspace before any real agent runs (unchanged); and an agent whose behaviour depends on the channel, which is the only thing that can make an arm difference appear.

### Multi-rater kappa coding (§53)

**Status: the code is built; the coding itself has not been executed.**

**Why it was deferred:** §53 concerns the *secondary* qualitative coding of
failure modes. The primary outcome (§38) is deliberately free of human
judgement, and it is the only thing this slice measures. Building the
machinery does not change that — `src/causalmesh/analysis/agreement.py`
has no import of `tasks.outcome` and feeds nothing back into
`TaskOutcome` or `AcceptanceDecision`; it computes *about* human
judgements an operator supplies, never *into* the automatic outcome.

**What is built.** A fixed, closed taxonomy of seven failure-mode
categories (`FailureModeCategory`), each traced to a concrete shape this
codebase can actually produce rather than a generic qualitative-coding
rubric — `STALE_READ_DIVERGENCE` from `TaskOutcome.divergence_absent`,
`CLOBBERED_WRITE` from the ownership-merge defect this file already
records, `DENIED_CLAIM_NOT_SURFACED` from the "enforcement was
unmeasurable" defect below, `POLICY_REFUSAL_MISHANDLED` from a recorded
`Verdict` refusal the agent's own recovery still failed on,
`UNRELATED_TEST_FAILURE` and `RUN_INCOMPLETE` from `TaskOutcome`'s own
fields, and `ACCEPTANCE_REJECTED_UNCLEAR_CAUSE` as the explicit catch-all
for a rejection the evidence tuple does not explain — coded as unclear
rather than forced into a category that does not fit, the same "unknown,
never a plausible zero" discipline AGENTS.md states for counters.
`RaterJudgement` records one rater's category for one run, validated
eagerly — an unknown category is refused, never coerced onto the nearest
known member. Cohen's kappa (2 raters) and Fleiss' kappa (N >= 2 raters,
refusing input with an unequal rater count per item rather than silently
dropping items) are implemented directly, no new dependency, each
returning a `KappaResult` that carries the observed and expected
agreement figures alongside the kappa value — the same evidence-retention
pattern `TaskOutcome.evidence` already follows, so a kappa number is
never reported detached from what produced it. `causalmesh agreement
<file>` runs it over an operator-supplied JSON or YAML judgement file.
17 tests in `tests/unit/test_agreement.py`, including both kappa formulas
checked against hand-computed worked examples independently re-derived
rather than asserted against the module's own arithmetic.

**What is not built, and cannot be from code alone: real raters.** No run
in this repository has been coded by a human, and no kappa value in this
project's history was computed from real judgements — `causalmesh
agreement` has never been pointed at anything but a smoke-test fixture.
The raters were always the hard part and remain it; this entry now
separates "the machinery does not exist" (resolved) from "the qualitative
coding has not happened" (still true), per `docs/PLAN.md`'s standing
commitment against fabricated results.

**What it would still take:** at least two people willing to read run
transcripts and code them against the taxonomy above, independently, and
a decision about which failed runs across which collections are worth
coding at all.

### Scaling beyond 4 agents (§86)

**Status: partly built (2026-09-30).** Delivery is selectable per run, the N-agent task is generated, and `causalmesh experiment scalability` measures delivered events and coordination bytes at N = 4, 8 and 16 for broadcast against path-scoped delivery. All of it runs on scripted mock agents, so it measures what the channel carries, not how agents coordinate.

**Why it matters:** broadcast fan-out grows quadratically with agent count, so a scalability profile needs an interest-scoped delivery policy to stay tractable. `PathScopedDelivery` was written for that and, until now, had no caller.

**What was built.**

- `policy_for_arm(arm, *, mode=None, interests=None)` in `relay/delivery.py`. `mode` is `"broadcast"` or `"path_scoped"`; unset is broadcast, so every existing caller is unchanged, and C0 is `NullDelivery` whatever the mode. `path_scoped` without an interest map raises instead of falling back to broadcast.
- `RunConfig.delivery_mode` (default `None`), added to `RunConfig.to_dict()` only when set, so an unset run serialises exactly as before. `execute_task` builds interests from the task's roles (`owns | depends_on`).
- `tasks/scaled.py`: `ScaledSpec(n_agents, group_size=4, own_files=2)` and `generate_scaled_task`, a deterministic generated task. Each agent owns a directory; agents are grouped and each group contests one shared registry file; family `concurrent_edit_collision`; it passes `validate_structure`. The fixture is written to a scratch directory per run, so nothing is added to `tasks/` or `fixtures/` and no existing plan, hash or run count changes.
- `experiments/scalability.py`: `scalability` (N in {4, 8, 16} x broadcast/path-scoped x C1/C2 x localized/dense contention = 24 runs) and `scalability_smoke` (4 runs). Kept out of `PROFILES` on purpose: `plan_experiment` multiplies tasks by arms by repetitions, and a profile of a different shape there would either change existing run counts or make `Profile` mean two things.
- `metrics/scaling.py` (`growth_exponent`, a log-log slope that is `None` when undefined and never 0; `summarize_scaling`) and `tasks/scalability.py` (`run_scalability`; `measure_run`, which verifies every chain offline; an ASCII `render_scalability`).
- `causalmesh experiment scalability [--profile scalability|scalability_smoke] [--seed S] [--json]`. It runs in a temp directory and writes nothing to the repository.

The four primary arms, `PROFILES`, `PROFILE_NAMES`, every profile's `run_count`, the 1920-run design, `plan_experiment` and the scheduler did not change.

**Note on §92 (no dead code): exception retired, with a qualification.** `PathScopedDelivery` now has a production consumer: `execute_task` installs it through `policy_for_arm` when a run is configured with `delivery_mode="path_scoped"`, and `causalmesh experiment scalability` reaches that. It is still not used by C0 to C3 as run by `causalmesh experiment run`, whose delivery stays broadcast, so the policy is consumed by the scalability profile and not by the primary design.

**What one run measured.** One run of the 24-run profile, on one Windows 11 machine (about 35 s), recorded by the implementer; it was not re-run on the machine that folded this note in. Deterministic for a given seed. Each agent produces 6 events, and these are properties of one generated scripted task:

- Broadcast delivered exactly 6 N (N-1) events: 72, 336 and 1440 at N = 4, 8 and 16. The fitted exponent over N = 4..16 is 2.16 (above 2 because N(N-1) is not a pure power; it tends to 2).
- With localized contention (each shared path contested by 4 agents however large N is), path-scoped delivery was exactly 6 N: 24, 48 and 96, exponent 1.00; at N = 16 that is 96 of 1440 events (6.7%). This follows from the topology the generator was told to build, which assumes each agent's neighbourhood stays small as N grows.
- With dense contention (every agent contests one path), path-scoped delivery removed a constant third (the events on private files) and the growth order stayed 2.16. Scoping only helps as far as interests are actually narrow.
- Bytes are not a clean power law. C1 (transcript) replays a shared room, so its bytes grew faster than events (exponent about 3.3 under broadcast). C2 (metadata, window 8) caps bytes per turn: about 1.9 under broadcast and about 1.0 path-scoped under localized contention. At N = 16 the C2 broadcast runs delivered 460 (dense) and 484 (localized) events an agent never saw, because the window cut them; path-scoped left none unseen under localized contention and 29 under dense.
- All 24 chains verified offline, and the scripted task succeeded in all 24 runs. That is a statement about a scripted task whose interests were declared to match the work, not about interest maps in general: a wrong map would silently starve an agent, and nothing here measures how often maps are wrong.
- Three agent counts are a coarse fit and two could not show a rate, so the points are printed next to the exponents. The mock agents have no randomness, so one run per cell is complete and a repeat gives the same head hash.

**What is not built:**

- The profile is not part of `causalmesh experiment run` or the scheduler: it is measured, not planned, randomized, indexed or resumed, and it writes no run artifacts under `data/raw`. Reason: it has no repetitions or tasks to randomize, and adding it to `PROFILES` changes what a profile means.
- Interests are declared by the harness and match the scripted work exactly. How wrong an interest map has to be before an agent is starved, and how agents should declare interests in practice, is unmeasured.
- One topology family only (contention groups of a fixed size, or one dense group). No chains, rings, hub-and-spoke or interest overlap between groups.
- Only N up to 16 was run (the generator accepts up to 99). Beyond 16 the exponent is extrapolation.
- Path-less events (list, test, intent, acceptance) are delivered to everyone by `PathScopedDelivery`; the profile's task emits none from agents, so the cost of scoping those is unmeasured.
- The growth statement is over delivered events and channel bytes, not tokens billed, latency or task quality. C3 (claims) is not in the default profile: one ad hoc C3 run at N = 8, path-scoped, failed the integration test because the shared registries are contested and the exclusive leases refuse the non-owner writers. One run, not a result.
- The C1 transcript `Room` appends a message for every delivery, so N-1 copies of each event enter the room under broadcast. That inflates C1 bytes beyond what one transcript per event would cost. It predates this change and is not corrected here.

**A counter not to read as a delivery count.** `MetadataChannel` re-counts its carried-over backlog into `events_available` on every turn, so summing that field across turns exceeds what the relay delivered (this profile found a 1440-event run reporting 3826). The profile counts what agents drained instead. The channel counter is left as it is because existing analysis reads it.

### The 1920-run confirmatory execution

**Status:** machinery built and tested; **gate closed**.

**Why:** executing the confirmatory collection commits to a preregistered
analysis, and this project has not preregistered one. `profiles.py` marks
it `gated=True`; `profile("confirmatory")` raises unless `allow_gated=True`
is passed explicitly.

**What it would take:** a preregistration, and the compute. Not a code
change — the code is finished and `test_the_confirmatory_profile_is_the_1920_run_design`
confirms the scale.

## The policy plane (built 2026-09-15, wired since)

`docs/policy.md` describes a contract, a gate and a ledger that generalise
enforcement from file paths to resources of four kinds — paths, spend,
endpoints and budgets. 88 tests cover it (38 at first build; more added as
checkpoints, identity and x402 landed) and `causalmesh policy check`
interrogates it. These are the gaps it still has, recorded before anyone has
to discover them.

### The gate is installable but not yet installed by default

**Status: resolved for `causalmesh experiment run`.** `ContractGate` in
`hooks/policy_gate.py` satisfies the same `Gate` protocol the arms already install, so
the lifecycle boundary takes it without a new code path, and it is covered by 12 tests.
`causalmesh experiment run` now discovers `causalmesh.yaml` the same way `causalmesh
serve` already does (`Contract.find(repo.root)`) and, when found, threads
`contract_path` into every run's `RunConfig` — reaching this path no longer requires an
operator to construct `RunConfig` by hand. A `--contract/--no-contract` flag (default
on) lets an operator skip discovery outright when they want the arms' bare gate with
certainty.

**Why this is safe for the experiment's own contrast.** The experiment's contrast is C2
against C3, and that is only clean if the two arms differ by one factor. Installing
`ContractGate` does not add a second factor: `_gate_for` (`tasks/runner.py`) keeps every
arm's own enforcement semantics even with a contract in play — C3 still enforces, C0/C1/
C2 still reach a verdict and allow anyway (§-referenced throughout `policy_gate.py` as
the counterfactual) — so the contrast is unaffected whether or not a `causalmesh.yaml`
happens to be present. This is why on-by-default is the right default rather than a
narrower opt-in: it closes the gap named here without touching what a confirmatory
collection would measure.

**What this does not change:** no profile gained a `contract_path` field.
`experiments/profiles.py`'s `Profile` is deliberately scale-only ("how many tasks, how
many repetitions... and nothing else"); wiring belongs at the CLI/runner boundary, where
`RunConfig.contract_path` already lived, not in the profile.

**Tested against the repository's own `causalmesh.yaml`**, not a fixture contract —
`tests/integration/test_cli.py::TestContractDiscovery` runs the real smoke profile
through the real CLI twice, asserting the run artifact's `provenance.contract_path` and
the presence (or, under `--no-contract`, absence) of `POLICY_VERDICT` events on the
resulting chain — proof the gate actually ran, not just that a path string was threaded
through.

**A bug this found in itself.** The first version returned a lease refusal
without recording a denial, because the policy gate consults leases through
`may_write`, which deliberately records nothing. That is the same defect
recorded below under "Enforcement was unmeasurable, not merely unmeasured".
It was caught by its own test rather than by a run, which is the outcome the
discipline is for.

### Spend is enforced, but nothing speaks x402

**Status: the gate-and-parse half is built.** `src/causalmesh/adapters/x402.py` parses a
real 402 challenge — V1's JSON body or V2's base64-encoded `PAYMENT-REQUIRED` header,
both verified against the reference implementation
(`github.com/coinbase/x402`, `python/x402/schemas/`) rather than written from memory —
into a `Resource.spend` and asks the already-tested `Gate` about it, returning a typed
`PaymentDecision`. `decide_payment` tries every accepted way to pay in the order the
server listed them and returns the first the gate allows, or the last refusal if none
are payable, so a server offering several payment options gets a real answer rather
than a decision based on only the first one listed.

**What this does not do, on purpose.** It does not sign a payment, hold a wallet or a
private key, or make the HTTP request itself. Actually paying needs a signer for one of
x402's payment schemes and networks — a real runtime dependency this project has never
carried, and AGENTS.md gates adding one without a reason that survives "what does this
cost a person installing the package." An operator's own payment code is the thing that
calls `decide_payment`, pays when it allows, and records the spend to `Ledger`
afterward — the module stops exactly where this project's own boundary is: the
financial audit layer, not a payment SDK. That check-then-pay is racy for a caller
that pays outside the gateway: the reservation that makes SDK totals atomic is not
taken on this path (see "Totals are reserved, then committed").

**What it would still take:** a signer, for whichever scheme and network an operator
actually needs to pay on, wired in as an operator's own dependency rather than this
project's.

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
is installed. See "The gate is installable but not yet installed by default" above for
the part of this story that is still open.

**A determinism bug this found, once a second consumer existed.** The verdict event's
timestamp was `utc_now_micros()` — real wall-clock time — in a chain whose every other
timestamp is `base_time_us + turn * tick_us`, deterministic by construction (§84). No
existing determinism test caught it, because
`TestDeterminism::test_two_runs_of_the_same_arm_agree` runs at C2 with no contract, so
no `POLICY_VERDICT` was ever on the chain it compared. Adding the unconditional
`ACCEPTANCE_DECIDED` event (see "Explicit acceptance decision object" below) put a
wall-clock timestamp on every run's chain for the first time, and that determinism test
immediately failed with two different `head_hash` values from two runs of the same
arm. Both events now use `post_run_time_us = base_time_us + max_turns * tick_us` — the
deterministic instant after the scripted turn loop ends. Recorded here rather than
silently folded into the acceptance-decision commit, because it is a correctness fix to
already-shipped code, not new behaviour.

### Checkpoints and identity, from parsed-and-ignored to real

**Status: resolved.** `policy.checkpoints` (human-in-the-loop) and `identity`
(per-agent keys) were accepted by the contract parser and read by nothing —
exactly the silent gap this file exists to prevent. Both are now real.

**`identity.keys`.** `Contract.identity_keys_dir` (`policy/contract.py`)
parses the directory `docs/FRAMEWORK-PLAN.md` proposed. `load_identity_keys`
(`crypto/keys.py`) loads one raw 32-byte Ed25519 seed file per agent
(`<dir>/<agent_id>.key` — the same seed shape `KeyPair.derive` already
produces internally, so an operator generating one by hand learns one
format). `execute_task` (`tasks/runner.py`) uses it in place of
`KeyPair.derive(master_seed, agent_id)` whenever a contract declares it; a
missing agent's key file is refused rather than silently derived, because
falling back would defeat the reason an operator declared external identity
at all — to stop keys being derived from a shared seed. A run using
`identity.keys` is not reproducible from `master_seed` alone (the keys are
external, out-of-band material), which is the correct tradeoff for a
deployment where participants must not share a derivation origin — the same
tradeoff `KeyPair.generate`'s docstring already named before this had a
contract-level switch.

**`policy.checkpoints`.** `Checkpoint` (`policy/contract.py`) parses
`{on, when, require}` rules in the shape `docs/FRAMEWORK-PLAN.md` proposed.
`evaluate_checkpoints` (`policy/checkpoints.py`) matches a checkpoint against
a resource's kind (`on`) and, for `spend` resources, a `when.usd` comparison
against the amount. `Gate.check` (`policy/gate.py`) consults checkpoints
after every other rule has already allowed — a resource already refused on
ownership or budget is not also put to a human, the same "cheapest and most
specific first" ordering the existing rules already followed.

**The decision is a synchronous callback, not a new concurrency model.**
`CheckpointHandler` is a plain `decide(...) -> (bool, str)` protocol, so the
gate stays synchronous end to end and the run loop needed no new blocking
primitive. `AutoDenyHandler` (the default) refuses every matched checkpoint:
an unattended run cannot honor `require: human`, and treating that as
approval would silently skip the safeguard the contract declared.
`ScriptedHandler` supplies a deterministic sequence of answers, which is what
keeps a checkpointed run reproducible (§84) the same way a scripted mock
agent does — a real human-attached handler (reading a terminal prompt, an
approval queue, anything with actual I/O) was left to whoever wires one in
when this was first written; a terminal one has since been built (see the end
of this entry).

**On the chain.** A matched checkpoint decision is signed and recorded as
`EventType.CHECKPOINT_DECIDED`, under a dedicated `checkpoint` identity —
distinct from `policy_gate`'s, the same way `ACCEPTANCE_DECIDED` already gets
its own `acceptance` identity, because a checkpoint decision is not itself
one of the gate's ordinary rule verdicts even though it reaches the chain
through the same `gate.verdicts` list.

**What this did not do, and now does in part (2026-09-30).** This entry originally said no human-attached `CheckpointHandler` shipped and nothing in the CLI prompted an operator. `TerminalCheckpointHandler` and `causalmesh experiment run --checkpoint-prompt` now exist, and the SDK forwards a handler (`CausalMesh(checkpoint_handler=...)`). The gaps that remain (approved checkpoints are not on the chain, the prompt blocks the calling thread, the handler is consulted on every arm, real terminals were not driven) are listed under "SDK claims and a human checkpoint handler" below.

## Items discovered during the build

Recorded as they were found, with the step that surfaced them.

### Parallel run execution (Step 10)

**Status:** the loop is sequential.

**Why:** runs share one machine, and a parallel scheduler would make
wall-clock timings depend on what else happened to be running. That is a
confound in the coordination-cost measurement (§44), which is an outcome of
the experiment rather than a diagnostic.

**What it would take:** per-run CPU and memory isolation, and a decision
about whether timing measurements remain comparable across a parallel and a
sequential collection. The index already supports it — `claim_next` is
atomic under concurrent workers and is tested with six real threads — so
the blocker is measurement validity, not mechanism.

### Docker as the C0 jail (Step 6)

**Status:** wired into `docker-compose.yml`, documented as optional.

**Why:** Windows has no `chroot` and no mount namespaces, so the L1 layer
is process separation rather than a filesystem jail. `docs/isolation.md`
states this precisely rather than claiming a jail that does not exist.

**What it would take:** running the harness on Linux or in CI, where the
container boundary is real. The three-layer model would then have a
stronger L1 without any change to L2 or L3.

### Timeout as a distinct run state (Step 10)

**Status: built, cooperative only (2026-09-30).** `ExperimentRunner(run_timeout_s=...)` runs each run under a whole-run watchdog (`_Watchdog` in `src/causalmesh/scheduler/loop.py`). When the budget lapses the run's task is cancelled, the agent loop in `execute_task` catches the cancellation, seals the chain it has (verdicts, then an acceptance decision, all at the fixed post-run simulated time) and returns a `RunResult` with `interrupted=True`. The scheduler records the run `TIMED_OUT`. It is opt-in: the default is no budget, so an unconfigured collection behaves and reproduces exactly as before. `causalmesh experiment run --run-timeout SECONDS` sets it; `--run-timeout 0` and negative values are refused rather than timing out every run.

This replaces the earlier position that `RunState.TIMED_OUT` existed in the state machine but nothing assigned it. The state was added first so that adding it would not mean changing a persisted schema; it is now reachable from a real run.

What a timed-out run leaves behind:

- **Partial evidence, kept.** The artifact carries the partial chain whole, and it verifies offline like any other. Partial workspace digests are kept too.
- **Outcome unknown, not failed.** The index records `succeeded=None`, and the artifact withdraws `result.outcome` (so every reader that looks for `outcome.succeeded` sees unknown) and keeps the half-finished workspace's score under `result.partial_outcome`. Counting a timeout as a task failure would claim a measurement nobody made.
- **Never accepted, and the chain says so.** The signed `ACCEPTANCE_DECIDED` event is `REJECT` with `run_interrupted_before_completion` in its evidence, via `decide_acceptance(outcome, interrupted=True)`. The default rule is unchanged.
- **Never retried.** `TIMED_OUT` stays terminal and non-retryable; `test_a_timed_out_run_is_never_retried` runs it through a real resume.
- **No wall-clock value in the signed chain.** Budget, elapsed time and grace are in `envelope.watchdog` on the artifact, outside the signature, and a test asserts every event timestamp sits inside the simulated clock's range. The artifact is marked `reproducible: false`, because where the cut lands depends on timing in general (with a mock agent that hangs at a fixed turn it is deterministic, and a test compares two timed-out runs' chains).

**What this does not do:**

- **Cooperative cancellation only.** Cancellation lands where an agent `await`s. A run wedged in a blocking call (a synchronous `subprocess.run`, a C extension, a model client with no async timeout) blocks the event loop itself, so the watchdog cannot fire at all. The integration check after the agents (`_run_integration_test`, up to 300 s, synchronous) is in the same position. Closing this needs the run to execute off the loop (a worker thread cannot be killed either, so realistically a subprocess per run), which also belongs with the per-run resource isolation "Parallel run execution" already needs.
- **A run that swallows cancellation is abandoned, not killed.** After the grace period (`timeout_grace_s`, default 30 s) the scheduler records `TIMED_OUT` with no chain (the artifact says `evidence: none: ...` and carries no `chain` key, so it reads as "no evidence" and not as "an empty run") and moves on. The orphaned task keeps running in the process. Tested with a deliberately stubborn agent.
- **The harness's own cancellation is still recorded as FAILED.** See "`_execute_one` catches `BaseException`" below.
- **One budget for every run.** No per-task or per-arm budgets, and the budget is not in the plan hash, so a resume may use a different one. That is deliberate for now (a timeout is an operational limit, not a factor) but it means two collections of the same plan are not guaranteed the same set of runs reaching `COMPLETED`.
- **Command-level timeouts are unchanged.** They still live in the tool layer (§22) and still surface as `CommandResult.timed_out`.

### Remaining task families (Step 9)

**Status: built and gated (2026-09-30). All four §35 families now have an authored task.** `interface_consumer` and `shared_utility_refactor` exist as `tasks/*.yaml` plus new fixtures (`fixtures/interface_consumer/`, `fixtures/shared_utility/`); no existing fixture was touched. With `schema_handler_widen` and `concurrent_edit_collision` that is four authored tasks, one per family, plus the synthetic CooperBench import.

**Why this waited:** §37 requires each task to *empirically demonstrate* its coordination dependency, which costs a C0-versus-C2 validation run per task. Building four tasks before validating one would have risked four tasks with the same defect. `concurrent_edit_collision` came first (Phase 0) and its real C3 run records a denial with actor, path and holder; building it exposed that the denial log had never been reachable from the gate at all, see below.

**What each new task builds.** Both are dependency-shaped, like `schema_handler_widen` and unlike `concurrent_edit_collision`: ownership is disjoint, `contested_paths` is empty, and one agent's write can invalidate the other's work.

| Task | agent_a (owns) | agent_b (owns, depends on) | Stale shape | Fails as |
|---|---|---|---|---|
| `interface_consumer` | `src/pricing.py`: `quote(item)` becomes `quote(item, region)`, no default | `src/cart.py`, depends on `pricing.py`, adds `receipt()` | `pricing.quote(item)` | `TypeError` at call time |
| `shared_utility_refactor` | `src/textutil.py` and `src/articles.py`: `slugify` becomes `make_slug(text, *, sep)`, old name removed, own caller migrated | `src/tags.py`, depends on `textutil.py`, adds `tag_feed_path()` | `textutil.slugify(` | `AttributeError` at call time |

They differ in more than naming: `interface_consumer` changes an arity; `shared_utility_refactor` renames and adds an option, and the utility has two callers owned by different agents, so the refactorer migrates the one it owns and can do nothing about the other.

**How the dependency exists by construction.** Three layers, not equally strong:

- *Structure:* agent_b declares the provider as a dependency and agent_a writes it. `validate_structure` accepts both tasks with zero errors and zero warnings.
- *Fixture:* the change is breaking, with no default argument and no alias, so a caller on the old shape fails the integration test.
- *Script:* agent_b's write is guarded by `if_informed_about` / `if_uninformed_about`, so what it writes depends on whether the channel told it about the provider's change. **This guard is authored, not discovered**; it is the mechanism `schema_handler_widen` uses.

**Real §37 verdicts** (`check_sensitivity`, the real C0-versus-C2 gate, mock agents, `repetitions=2`, recorded by the implementer): both tasks **SENSITIVE**, C0 0/2 and C2 2/2, with 2 divergences in C0 and 0 in C2. The tests pin the `repetitions=1` counts (C0 0/1, C2 1/1, divergences 1 and 0), as the existing tasks' gate tests do.

**All four arms, one run each, same seed:**

| Task | C0 | C1 | C2 | C3 | Coordination bytes (C0 / C1 / C2 / C3) | C3 denials |
|---|---|---|---|---|---|---|
| `interface_consumer` | fail | succeed | succeed | succeed | 0 / 372 / 199 / 199 | 0 |
| `shared_utility_refactor` | fail | succeed | succeed | succeed | 0 / 691 / 425 / 425 | 0 |

C0 fails on both criteria (tests fail and the marker remains) for the intended reason: the failing output in C0 is the `TypeError` or `AttributeError` above, read from the integrated workspace rather than inferred. C2 and C3 spend identical coordination bytes, as they must. C3 holds a lease on every owned path and refuses nothing, because nobody writes outside their ownership; enforcement has nothing to do on either task, the same result `schema_handler_widen` gives and the opposite of `concurrent_edit_collision`.

**What carries the verdict.** To check the SENSITIVE verdict is not only the guard, the provider was rebuilt backward-compatibly (a default argument for `quote`; `slugify = make_slug` left behind as an alias) and the uninformed consumer run again in C0. Its stale call shape then works and the integration tests **pass**, yet the run still fails, because §38 also requires the divergence marker to be absent and the marker is a string match on the stale call shape. So the verdict is carried jointly by the breaking change and by the marker; the marker alone would call a harmless stale call a failure. That is a property of the §38 rule as implemented, not something these tasks introduced, and it is pinned in `tests/integration/test_task_families.py::TestTheDependencyIsTheBreakingChange`.

**A side effect on the confirmatory plan.** `experiment plan --profile confirmatory --allow-gated` plans every authored task in `tasks/`, so it now returns 1920 runs (120 repetitions x 4 arms x 4 tasks), matching the design the spec names, where it returned 960 with two tasks. `tests/integration/test_cli.py::TestPlan::test_the_gate_opens_when_asked_explicitly` was updated from 960 to 1920. The gate on the confirmatory profile stays closed and nothing was executed. Only the plan grew, and all four tasks' C0-versus-C2 contrast comes from authored scripts.

**A false NOT SENSITIVE the first gate run produced, and why it is recorded** (see also "The section 37 gate cannot tell a missing test runner from no effect" below). The first run returned NOT SENSITIVE, C0 0/2 and C2 0/2, for both tasks. The cause was the environment: the harness runs `python -m pytest` with the `python` on `PATH`, and in that shell it had no pytest, so the integration test exited non-zero in every arm. Divergence counts still separated the arms (2 versus 0), but success did not. With the venv first on `PATH` the same code returned SENSITIVE. Nothing in the task definitions changed between the two runs.

**What this does not claim.**

- **Nothing about agent behaviour.** Every run used a deterministic mock agent whose branch is chosen by the script. SENSITIVE says the authored construction separates C0 from C2 when an agent acts on the information it gets, not that a real model would act on it, or would have made the stale call in the first place.
- **The verdicts are close to tautological by design.** The scripts write the stale shape when uninformed and the current shape when informed, and the marker detects exactly that. The gate confirms the construction is wired correctly (the informed channel reaches agent_b, the stale branch really breaks the test, the integration and marker checks agree). It is not an independent estimate of how often real agents would break such an interface.
- **No realism claim for the fixtures.** Both are a few dozen lines written for the task, not drawn from real repositories.
- **No size claim.** One scripted pair per family, single seed, at most two repetitions. The mock is deterministic, so repetitions add no variance; they only confirm the result reproduces.
- **Enforcement is not shown to help or hurt here.** C3 equals C2 on both, for lack of any contested path. The only task that exercises the gate's refusal path remains `concurrent_edit_collision`.

**What it would still take:** a dependency-shaped family where the stale shape is not a literal in the script, for example a real model writing the consumer after an observed interface change, so that informed and uninformed behaviour is measured rather than authored; a gate that reports a missing test runner as "could not run" instead of as a failed arm; and a divergence rule that does not depend on a string marker alone.

### Enforcement was unmeasurable, not merely unmeasured (Phase 0)

**Status:** fixed.

Denials were written only by `ClaimRegistry.acquire`, while the C3 gate
refuses writes through `may_write`. Every block the gate performed was
therefore invisible to `denials()` — the method whose own docstring calls
it "the core enforcement measurement". A real C3 run reported 2 claims held
and 0 denials while enforcement was working correctly.

This was worse than a missing feature. A measurement that cannot observe
its own subject reports a confident zero, and "C3 never blocked anything"
would have been recorded as a finding rather than a defect.

The fix keeps the two acts separate: `may_write` stays read-only, because
it is an advisory query callers may make speculatively and recording there
would count questions rather than blocks. `record_denial` is the explicit
statement that a real attempt was refused, and `ClaimGate` calls it.

### Ownership merge could not express a contested path (Phase 0)

**Status:** fixed.

The integration merge took every file from its declared owner, so on a
contested path the non-owner's write was discarded in *every* arm — the
contest was resolved before the arms could differ, and the task measured
nothing.

Contested paths are now excluded from the ownership rule and resolved from
the **signed chain**: the last agent whose accepted write event names the
path wins. Two wrong versions preceded that:

- Alphabetical order, described as "last writer wins". It is not. Under C3
  agent_b's write was refused, so its workspace still held the untouched
  fixture, and that empty copy overwrote agent_a's successful write purely
  because "agent_b" sorts later. C3 appeared to lose both registrations
  when it had preserved one.
- Matching event types in lowercase when the chain serialises them
  uppercase. The lookup silently matched nothing, every contested path fell
  back to the fixture, and all four arms failed identically — which looks
  like a broken task rather than a broken lookup.

Filesystem mtimes were rejected as the ordering source: coarse resolution,
and they record when a file was touched rather than which write the system
accepted. The relay's monotonic sequence is authoritative, and a denied
write produces no event at all, so a blocked agent cannot win a contested
path by construction.

### Staleness estimation (§23, §45)

**Status:** not built. The coordination-cost half of Step 11 is.

`metrics/` aggregates what the channel recorded — bytes, tokens, events
available versus injected, per-arm and per-task — and `causalmesh analyze`
reports it alongside the four planned contrasts. That part needed no new
instrumentation: the run artifacts already carried every figure.

The staleness half does. `docs/PLAN.md` names λ̂, δ̂ and Δ̂ as the estimators
to produce, and no definition of them exists in this repository. They come
from §23 and §45 of the specification, which the build has been working
from but which is not checked in.

**Why it was not inferred from the data.** The per-turn observations record
which events each agent saw and when, so *an* estimator could be derived
from them. A derived estimator would carry the same symbol as the specified
one while possibly measuring something else, and a number whose definition
is reconstructed from its inputs is exactly the kind of figure §68 exists to
prevent. The honest form of "not specified here" is an empty module and this
entry, not a plausible formula.

**What it would take:** the §23 and §45 definitions. The instrumentation to
feed them is already persisted.

### A channel bypass passed every test (Phase 1)

**Status:** fixed.

Feeding delivered events straight into a model's conversation — bypassing
the coordination channel entirely — passed all 21 adapter tests.

This is the most serious defect available in this codebase. Peer
information would reach an agent's context outside all accounting, so the
coordination-byte total would no longer be a complete account of what the
agent knew, and the C0-versus-C2 contrast would measure something other
than information. C0 stayed safe only incidentally, because `NullChannel`
raises on non-empty input; under C2 the leak would have been silent.

`test_the_channel_is_the_only_route_information_takes` now closes it.

The general lesson, recorded because it will recur: **the guarantees most
worth testing are the ones no test naturally covers, because they are
properties of what the code does not do.** Every test written so far
checked that something happened correctly. Nothing checked that nothing
else happened.

## Jev decision engine

### Adapter built, not wired

**Status:** `JevClient` and the Choice/Score/Noul request and response types exist in
`src/causalmesh/jev/`, tested at the unit level with no network and, when
`TYPESAFE_API_KEY` is set, against the real `api.typesafe.ai` endpoint. Nothing in the
runtime calls it — no run, no decision, no chain event depends on Jev today.

**Why:** every decision point that exists in the runtime — `TaskFamily`,
`check_sensitivity`'s C0-vs-C2 verdict, every rule in `policy/gate.py` — is
deliberately deterministic, and for good reason: §35/§36 require task properties to be
declared rather than inferred so a run stays reproducible and hash-pinned, and the
gate's rules (ownership, allowlist, ceiling, budget, claim) each have exactly one
correct answer given the contract and current state. There was no decision point in
the current runtime where trading a deterministic answer for a calibrated probability
was the right move — that would add latency, a network dependency, and a new failure
mode to a call that already had one correct answer.

**What it would take:** a decision that is genuinely uncertain given the available
state, not merely unautomated. The leading candidate is `recover` (retry the same
agent, switch to a different one, or escalate to a human) once multi-agent
orchestration exists — see "Agent handoff package on recovery" below. Wiring Jev into
`classify` or `accept` before then would be adding a probabilistic call to a decision
that already has a correct deterministic answer, which is the trap this entry exists
to name and avoid.

### Explicit acceptance decision object

**Status: built.** `AcceptanceVerdict` and `AcceptanceDecision` live in
`src/causalmesh/tasks/outcome.py`; `decide_acceptance(outcome)` is a total function of
`TaskOutcome.succeeded` (§38's own rule, named rather than re-derived). `execute_task`
emits one `EventType.ACCEPTANCE_DECIDED` chain event per run, unconditionally, signed
under a dedicated `acceptance` identity — never an agent's key and never
`policy_gate`'s, because accepting a result is a decision distinct from both what an
agent did and what the policy plane allowed. `RunResult.decision` carries it
alongside `outcome` so callers don't have to re-scan the chain for it.

**A stale claim corrected.** This entry previously said the work was blocked on a
contested-path task that "does not exist yet." It already did:
`concurrent_edit_collision` (§74's task) was built and tested before this entry was
last edited. `tests/integration/test_collision_task.py::TestAcceptanceDecisionsOnTheChain`
is the test that needed a genuinely contestable task to be meaningful — it runs all
four arms, where C0 and C3 both fail for different reasons, and proves the decision
tracks `outcome.succeeded` exactly and verifies offline with no special-casing.

**What this does not change:** `HUMAN_REVIEW` is declared in `AcceptanceVerdict` but
unreachable — the rule here is total over `ACCEPT`/`REJECT`, the same way
`RunState.HANDED_OFF` is declared before anything assigns it. **What it would still
take:** wiring the Jev adapter in as a `Choice` call among the three verdicts, which
needs a decision that is genuinely uncertain given current state — this rule isn't
one, by design (see "Adapter built, not wired" below).

### Agent handoff package on recovery

**Status: prerequisites built (2026-09-30); nothing uses them.** The two things this entry said had to exist first now do, and nothing else does. The scheduler still runs exactly one agent per run and never assigns the new state.

- **A scheduler state.** `RunState.HANDED_OFF` ("run continues under a different agent"), additive in `scheduler/states.py`. Legal transitions: `RUNNING -> HANDED_OFF`, and out of it to `RUNNING` (the continuation) or `ABANDONED`. It is not terminal and not retryable (a cold re-run would discard the work being handed over). `RunIndex` (`storage/index.py`) gains `hand_off()` and `continue_handed_off()` so the state is writeable through the same transition-checked path as the rest, and `abandon_running()` now also sweeps `HANDED_OFF` at startup (a run waiting for a continuation that only a live process could start is stranded in a single-process loop), recording the state it actually found in the transition log.
- **A record shape.** `HandoffPackage` in `scheduler/handoff.py`: run and task identity (`task_hash` pins the task's content), `from_agent` and `to_agent`, a single `repository_digest`, the `diff` so far, `test_results`, `prior_decisions` (by chain event id), frozen, with `to_dict`/`from_dict` and canonical `to_json`/`digest`. `diff` and `test_results` are `None` when not computed and `()` when computed and empty; `to_agent` is `None` until a recovery decision picks one; a test result's `exit_code` and `passed` can be unknown. No timestamp, host or absolute path can enter it (paths are validated repository-relative), so the same handoff serialises to the same bytes and could later be committed to by hash without touching a bit-reproducible chain.

**Persisted-schema implications.** None that need a migration. `runs.state` and `transitions.to_state` are free `TEXT` with no `CHECK`, `counts()` iterates `RunState.ALL` so the new state shows up as a zero, and a database written before the state existed reads unchanged (tested). The direction that does not work is the reverse: an older build reading a database that contains `handed_off` rejects the row in `check_transition` (unknown state). That cannot happen yet, since nothing assigns the state, and it is the reason the addition should ship before the code that assigns it. `tui/monitor.py` knows the state (styled, counted as in-flight).

**What it would still take** (none of this is built):

- A **producer**: something that builds a `HandoffPackage` from a live run. The repository digest and diff need a defined baseline (the fixture at run start), and the workspace digests `execute_task` already computes are the raw material, but the single `repository_digest` is not computed anywhere, so its definition (which files, how ordered) is still open. Test results have two candidate sources (the agent's own `TEST` events and the harness's integration check), and which one a handoff carries is undecided.
- A **chain event** for the handoff (a new `EventType`, which is a schema change to `events/` and `docs/protocol.md`), signed by an identity that is neither agent's nor `policy_gate`'s, committing to the package by `digest()`. Until then a handoff would be an unsigned fact about a signed chain.
- A **consumer**: a second agent that is actually given the package, which is the multi-agent orchestration this entry has always been waiting on.
- The **`recover` decision** (retry the same agent, switch agents, escalate) that would assign the state, which is where the Jev adapter becomes useful.
- A decision on what `attempts` means across a handoff. `continue_handed_off()` leaves it alone (a continuation is not another attempt), a choice nothing has yet tested against a real use.

### Causal edges over the chain

**Status: two relationships populated, and a CLI reader built (2026-09-30).** Store and query surface built and tested (`src/causalmesh/edges/`, `tests/unit/test_edges.py`, 25 tests). `execute_task` (`tasks/runner.py`) populates, on `RunResult.edges` (and therefore in the run artifact, alongside `chain`):

- a `REQUIRED` `CausalEdge` from a denied write's `FAILURE` event back to the `POLICY_VERDICT` event that refused it, whenever a contract is installed and refuses at least one call. `tests/integration/test_task_execution.py::TestCausalEdgesForDenials` proves it end to end: every denied write in the scenario gets exactly one edge, pointing at a real verdict event that is itself a refusal.
- a `REQUIRED` edge from the `ACCEPTANCE_DECIDED` event to an `INTEGRATION_TEST_RESULT` event, one per run, appended after the denial edges (below).

`causalmesh analyze --edges` reads the edges back out of run artifacts. `EdgeIndex` stays in-process; the CLI reads artifacts, not an index.

**The integration test result is now a chain event.** `execute_task` already ran the task's integration test (`_run_integration_test`, the harness measuring the result, outside the agents' tool boundary) and fed its exit code to `evaluate_outcome`. It now also records it as `EventType.INTEGRATION_TEST_RESULT` under a dedicated `integration_test` identity (key derived from the master seed, like `acceptance` and `policy_gate`), immediately before `ACCEPTANCE_DECIDED`. It is a new type rather than a reuse of `EventType.TEST`: `TEST` is an agent running tests in its own workspace, and the two must stay distinguishable on the chain.

**Why this does not compromise reproducibility.** The timestamp is `post_run_time_us` (`base_time_us + max_turns * tick_us`), the same deterministic instant the verdict and acceptance events use; no wall clock. The payload is exactly `{command, exit_code, ran}`: the task's fixed command and the exit code. Stdout, stderr, duration and the integrated workspace path are deliberately absent, because `pytest -q` prints elapsed time and the workspace lives under a temp directory. A test that never ran (timeout or `OSError`) is `exit_code: null, ran: false`, not a 0. The exit code was already inside the chain as `integration_test_exit_code=N` in the acceptance evidence, so this adds no new source of variation, only a second place the same value is signed. `TestDeterminism::test_two_runs_of_the_same_arm_agree` still passes, and `TestAcceptanceEdge` pins the exact payload key set, that two runs produce identical `chain_hash` and `signature` for the new event, that a chain holding it verifies offline after a round trip through a JSONL file against a key ring rebuilt from the seed, and that editing the recorded exit code breaks verification.

**What the acceptance edge claims.** `acceptance -> integration test`, `REQUIRED`, not `CAUSED`, on purpose: `decide_acceptance` is a function of `outcome.succeeded`, which is `tests_passed AND divergence_absent`, and the divergence-marker check reads the integrated workspace and is not a chain event. The test result is a necessary input, not the sole cause, and the edge's `note` says so. Both endpoints exist on the chain (`TestAcceptanceEdge::test_every_edge_endpoint_is_a_real_chain_event`).

**Side effect to know about.** Every run's chain gains one event, so `head_hash` values recorded before this change no longer match a re-run. Two runs of the same arm agree with each other, which is what the determinism test checks; a stored pre-change hash is a statement about the old chain. `run.json` artifacts from before this change verify as they always did.

**`causalmesh analyze --edges`.** It follows the existing command's conventions: `--json` is the machine path, tables carry a label (per-edge rows `[PILOT]`, counts by kind `[DERIVED]`), and the JSON payload carries `"label": "PILOT"`, descriptive only. It shows counts by relationship kind (every kind listed, so a real zero reads differently from a missing kind), and per edge both event ids with a label resolved against the artifact's own `chain` (for example `FAILURE by agent_b, denied`, `ACCEPTANCE_DECIDED by acceptance, ACCEPT`, `INTEGRATION_TEST_RESULT by integration_test, exit code 0`). An id the chain does not contain reads `unresolved`; an artifact with no chain reads `unknown`. Labels are ASCII (non-ASCII payload text is backslash-escaped) and Rich escapes them so a `[tag]` in a payload is not read as markup.

**A shipped behaviour changed, and why.** For a run whose artifact has no `result.edges` key the answer is `unknown`, not 0. `edges_for_run` used to read a missing key as an empty tuple, which the old CLI then summed into `total_edges: 0`, the confident zero AGENTS.md forbids. `RunEdges.recorded` now separates "recorded none" from "predates edges"; `total_edges` and `by_relationship` are `null` when nothing counted was recorded and otherwise count only the runs that recorded, with `runs_edges_unknown` beside them. Per-run JSON has `edges: null`, not `[]`, for an older run.

**`Event.parent_id` was considered and rejected as the population source.**
`ToolExecutor` sets `parent_id` to `last_observed_event_id` — the last peer event an
agent drained before acting, not necessarily the event that caused the specific call
that followed. An agent can observe one event and then take several unrelated actions
in sequence, all carrying the same `parent_id`. Auto-deriving a `CAUSED` edge from it
would be exactly the kind of plausible-but-possibly-wrong inference §68 exists to
forbid — the same reasoning that keeps the §23/§45 staleness estimators out of this
repository rather than reconstructed from their inputs (see "Staleness estimation"
below). `Event.references` remains unused by any production call site; it is still a
candidate for whatever population source comes next, on the same "only from a call
site that already knows the relationship is real" standard as the one shipped here.

**Why the denial-to-verdict edge is exact rather than a best-effort match.**
`Verdict.to_dict()` records the resource, rule, holder and reason but not which agent
was denied, so pairing a `POLICY_VERDICT` to a `FAILURE` event by content (path, rule,
reason) would misattribute the moment two agents are denied identically in one run —
a real shape under `concurrent_edit_collision`, where both agents contend for
`src/config.py`. The fix pairs by position instead: `gate.verdicts` and the chain's
denied `FAILURE` events are both produced by the same sequence of calls through
`LifecycleBoundary.invoke`, one verdict and (on refusal) exactly one `FAILURE` event
per mutating call, in the same order — so the Nth refused verdict is provably the Nth
denial, with no content matching involved. `execute_task` raises rather than pairing
if the two counts ever disagree, so a violated assumption becomes a loud failure
instead of a silently wrong edge.

**A bug this found in itself.** The first version filtered denied events on
`payload["outcome"] == "DENIED"`; `ToolOutcome` is a lowercase-valued `StrEnum`
(`hooks/lifecycle.py`), so the real value is `"denied"` and the filter matched
nothing. The positional-count invariant above caught it immediately — a real C3 run
that denies a write reported 1 refused verdict and 0 matched denials, which raised
rather than silently returning zero edges. This is the same defect class as
"Enforcement was unmeasurable, not merely unmeasured" below: a filter that looks
plausible and matches nothing is worse than one that errors.

**What it would still take:**

- *More population sources.* Two relationships are populated. `Event.parent_id` is still rejected as a source (above). `Event.references` is still unused by any production call site. `CAUSED`, `RECOVERED` and `SUPERSEDED` have no writer at all: `RECOVERED` needs the handoff record from "Agent handoff package on recovery", and `SUPERSEDED` needs a call site that knows one event replaces another, which no current one does. The divergence check is the acceptance decision's other input; it could become a chain event the same way the test did, which would let the edge become two edges, but it is a workspace inspection with no natural exit code and that was not attempted.
- *The positional denial pairing is untouched.* It still raises if the verdict and denied-event counts disagree.
- *The analyze surface reads artifacts, not `EdgeStore`.* Edges recorded by a caller through `EdgeStore` rather than by `execute_task` are not visible to it.
- *Label resolution is by id, for the four event types it knows how to describe.* Any other event type gets `TYPE by actor` with no detail, which is accurate but terse.
- *No `--edges` filter by kind or run.* The table lists everything; `--json` plus `jq` is the filter today.
- *Platform runs.* Checked on Linux only; per `scripts/check.py`, Windows and macOS each need their own run.

## Standalone adoption (built 2026-09-24)

`docs/superpowers/specs/2026-09-24-standalone-adoption-design.md` designed three
concrete surfaces for gating a real coding agent's writes in an operator's own
project, outside a CausalMesh checkout. All three are now real and tested;
`docs/adoption.md` is the wiring guide.

**Status: shipped.**

- **`causalmesh policy check --stdin`** (`src/causalmesh/cli/commands_policy.py`).
  Reads `{"agent_id", "kind", "name", "amount"?, "unit"?}` as one JSON object from
  stdin and feeds it through the same `_build()`/`Gate.check()` call the existing
  `--agent`/`--kind`/`--name`/`--amount` flags already use — a second input path,
  not a second code path. A malformed payload or a missing required field is a
  usage error (exit 2) with a hint, the same discipline `_load_or_exit` already
  applies to a broken `causalmesh.yaml`. When both `--stdin` and the flags are
  given, the explicit flags win — `--stdin` is a mode switch, not a silent merge.
  6 tests in `tests/integration/test_cli.py::TestCheckStdin`.
- **The Claude Code hook adapter** (`docs/examples/claude-pretooluse.sh`). Adapts
  Claude Code's `PreToolUse` hook payload (`{tool_name, tool_input}`) to
  `policy check --stdin`, and the verdict back to the
  `{hookSpecificOutput: {permissionDecision, ...}}` shape Claude Code expects.
  Which tool names count as path writes (`Write`, `Edit`) is a property of the
  harness, not of CausalMesh, so that mapping lives in the adapter script, not
  the core CLI — another harness's hook protocol needs its own adapter, following
  the same pattern. Run for real, not merely documented, by
  `tests/integration/test_adoption_hook.py` against a synthesized hook payload
  and a contract with two roles (so a denial is a genuine ownership refusal, not
  an undeclared-and-therefore-unrefused path). This is purely ephemeral: no
  chain, no ledger, no run — it answers one question and exits, same as
  `policy check` always has.
- **`docker/Dockerfile` and `docker-compose.yml`** package the already-standalone
  `causalmesh serve`, no `causalmesh.yaml` baked into the image, bind-mounted
  read-only at run time instead.

  **Regression found and fixed 2026-09-30.** The paragraph above originally
  described `serve` as using only `http.server` from the stdlib, needing
  just the four base runtime dependencies. That was true when it was
  written; it stopped being true when `causalmesh serve` moved onto FastAPI
  (Phase 2A, `d7e02ce`) — `commands_serve.py` now imports `uvicorn`
  unconditionally and fails with "uvicorn is required" if it is missing.
  The Dockerfile still ran a bare `pip install .`, so the image it built
  could not actually start `serve`; the CLI's own mandatory-auth check
  (`--api-token` required unless `--dev`, and `--dev` is refused for any
  non-localhost `--host`, which `--host 0.0.0.0` always is) meant
  `docker-compose.yml` would have failed a second, independent way even
  with the dependency fixed, since it passed no token. Nobody re-ran the
  container after the FastAPI migration to catch either.

  Fixed: the Dockerfile now installs `.[server]`, and `docker-compose.yml`
  passes `CAUSALMESH_API_TOKEN` through from the environment.
  **Re-verified by hand in this environment** (Docker Desktop, real
  `docker build` + `docker run`, not asserted from reading the Dockerfile):
  build succeeds, the container starts, `GET /healthz` returns 200,
  `GET /v1/tools` without a token returns 401, and with the correct
  `Authorization: Bearer` token returns 200. `docker compose up` was then
  run for real against the final tree: the same 401/200 results held on
  `/v1/tools`, `/v1/tools/{name}/execute` and `/v1/chat/completions`, and
  with `CAUSALMESH_API_TOKEN` unset the container exits with code 2 and
  "--api-token is required" instead of starting unauthenticated.

**What does not ship:**

- No published registry image (`causalmesh/causalmesh:latest`). The Compose
  example in `docs/adoption.md` builds from the Git repository until one exists.
- No persistence of real-world verdicts from either path. `policy check --stdin`
  (and the hook that wraps it) is stateless by design, matching `policy check`
  itself; `serve` gates and forwards but this adoption path does not wire its
  recording to a location outside a CausalMesh checkout.
- No adapter for any harness other than Claude Code. The `PreToolUse` JSON shape
  is specific to it; adopting another harness needs its own adapter script.

**A pre-existing test-infrastructure gap found while verifying this, not caused
by it.** `tests/integration/test_cli_init_quickstart.py::TestQuickstartEndToEnd`
asserts on `result.stdout` for text that `causalmesh quickstart` actually writes
through `note()`, which prints to *stderr* (`err_console`, `_output.py`) —
correct, since these are progress notes, not command output. It passed under
whatever `click`/`typer` version was pinned when the test was written, when
`CliRunner`'s default capture mode still merged the two streams into
`result.stdout`. `click==8.5.0` (current, unpinned upper bound in `pyproject.toml`) replaced the
older `mix_stderr` constructor flag with separate-by-default capture, so
`result.stdout` no longer includes what a command wrote to stderr — the
assertion now fails against real, correct CLI behavior. Confirmed present on
this branch's `HEAD` before any change in this pass (`git stash` + rerun), not
a regression this work introduced.

**Resolved 2026-09-28.** The Phase 1 SDK commit deleted the two assertions
instead of fixing them. They are restored and now read `result.output`, which
holds both streams under every `click` version, so the tests again check
that quickstart reported what it did rather than only its exit code.

## Developer SDK (Phase 1, landed 2026-09-27)

`causalmesh.sdk`, `causalmesh.gateway` and `causalmesh.integrations` let an
operator put the existing gate in front of their own agent's tools:
`CausalMesh.from_config(...)`, `register_tool(Tool(...))`, `execute(...)`.
There is one authorization path. The SDK reuses `ContractGate`,
`LifecycleBoundary` and `Relay`; it adds no policy logic of its own.

**Status: shipped, with defects found in review and fixed on 2026-09-28.**
Each fix is pinned by `tests/sdk/test_evidence.py`, and each was
mutation-checked: reverting the fix makes a test there fail.

- **A second agent's calls ran unrecorded.** The relay was given a key for
  the default agent only, so any other `agent_id` executed and its event
  was refused, with `event_id=None` and no error. Keys are now issued to
  the default agent, every `roles` entry and anything in `agents=`. Any
  other agent raises `UnknownAgentError` before the gate or handler runs.
  When the relay refuses or fails on an event anyway, the result reports it
  (`recorded is False`, `audit_error`) rather than dropping it.
- **Read-only tools were recorded as `WRITE`.** The event type was chosen
  by whether the call had a path. It now follows `Tool.mutating`.
- **A tool registered without `mutating=` skipped the gate.**
  `Tool.mutating` now defaults to `True`. Only an explicit `mutating=False`
  skips the gate.
- **Unenforced arms were silent.** On C0-C2 a call that C3 would refuse
  now comes back with `would_refuse`, `shadow_rule` and `shadow_reason`.
  The signed event records `would_refuse` too. `CausalMesh.enforcing`
  states the arm's behaviour. Enforcing only on C3 is unchanged; `serve`
  and the harness do the same.
- **Keys came from a hard-coded public seed**, so anyone could sign as any
  agent. Keys now come from `identity.keys` when the contract declares it,
  otherwise from a caller-supplied `seed=` (reproducible), otherwise from
  fresh random keys, as `serve` does.
- **The run id was a random `uuid4`** inside the signed identity, which
  broke chain reproducibility. It now defaults to the constant `"sdk"`, and
  callers pass their own when they keep several chains.

**What did not ship at first, and what has since been built (2026-09-30):**

- **Framework adapters: Generic, OpenAI, LangChain, Anthropic, LangGraph, CrewAI built; no hosted model has driven any.** `GenericAdapter`, `OpenAIAdapter` (function calling, no vendor SDK; `schema.py` derives JSON Schema from the handler's own signature) and `LangChainAdapter` came first; `AnthropicAdapter`, `LangGraphAdapter` and `CrewAIAdapter` followed. Every adapter routes exclusively through `BaseFrameworkAdapter.observe`/`aobserve`, which call `CausalMesh.execute`/`execute_async`, so there is one authorization path whichever framework calls in; none constructs a second gate or calls a tool's handler directly. See "Framework adapters: Anthropic, LangGraph, CrewAI" below for what is built and what was never run.
- **Human-in-the-loop approval from the SDK: built.** `CausalMesh(checkpoint_handler=...)` forwards a handler to the gate, and `TerminalCheckpointHandler` is a human-attached one. Without a handler a matched checkpoint still refuses by default. Gaps are listed under "SDK claims and a human checkpoint handler" below.
- **Claims: built, opt-in.** `CausalMesh(claims=ClaimRegistry(...))` and explicit `mesh.claim()`; the default is still off (`registry=None`), and there is no acquire-on-first-call. See the same entry.
- **Persistence: built for the SDK session, not for `serve`.** `CausalMesh.export(directory)` writes `run.json` and `keyring.json` for `causalmesh verify --run`, and `persist_to=` appends the chain as it goes. See "SDK export and verification" below.
- **Wall-clock timestamps in the signed chain: fixed for the gateway and, from 2026-10-12, for the chat path.** The gateway signs a per-session logical clock and keeps the wall clock in the unsigned envelope, so the SDK and `serve`'s `/v1/tools/{name}/execute` are reproducible, and `/v1/chat/completions` now stamps on the same clock. See "A logical clock in the signed chain" below and "The chat path signed the wall clock".
- **Reads are not gated.** `mutating=False` tools go around the gate, as
  §20 defines for the experiment. An operator who wants reads checked has
  to declare those tools mutating.

### Framework adapters: Anthropic, LangGraph, CrewAI (2026-09-30)

**Built.** `AnthropicAdapter` (Anthropic Messages `tool_use` blocks in, `tool_result` blocks out with `is_error`, tool definitions with `input_schema`; no vendor SDK, accepts plain dicts or SDK block objects; `handle_tool_use(s)`, `handle_message` and `a`-prefixed twins), `LangGraphAdapter` (the LangChain adapter's tools plus `tool_node()`, a real `langgraph.prebuilt.ToolNode`) and `CrewAIAdapter` (`crewai.tools.BaseTool` subclasses that route through the gate, sync `_run` and async `_arun`), each with a sync and an async path, exported from `causalmesh.integrations`, with the import guard pattern of `LangChainAdapter` (importing the package works without any framework; constructing an adapter without its framework raises `ImportError` naming it). All route through `BaseFrameworkAdapter.observe`/`aobserve` and the `Observation` it returns, the single place a model-requested call becomes text, so every adapter classifies errors the same way; `bind_arguments` serves adapters that receive positional or keyword arguments. Model mistakes come back as `Action failed:` answers; an unknown agent raises `UnknownAgentError` before the gate or the handler, on the sync and async paths, through every adapter.

Pinned by `tests/integration/test_adapter_gate.py` (one set of safety properties run through every adapter: an allowed call goes through the gate and is recorded, a denied call never reaches the handler, model mistakes are answers, an unknown agent raises before gate and handler, all on the async path too, plus a check that no adapter module calls a handler), `test_anthropic_adapter.py`, `test_langgraph_adapter.py`, `test_crewai_adapter.py` and `tests/unit/test_adapter_helpers.py`. The gate property was mutation-checked: making the Anthropic, CrewAI, LangChain (async) and OpenAI (async) paths call the handler directly, and making the shared helper swallow every exception, each fail tests.

**Fixed on the way.** `LangChainAdapter` tools raised `MissingResourceError`/`ToolNotFoundError` out of the caller's loop on a model's bad call; they now return `Action failed: ...`, as the OpenAI adapter already did, which is what lets them survive inside a LangGraph `ToolNode` (it re-raises by default). `tool_to_json_schema` dropped every parameter when one annotation could not be resolved, described `Optional[int]` and `X | None` as `string`, listed `*args`/`**kwargs` as required-looking properties and ignored `Literal` and list item types; it now unwraps `Optional`, emits `enum` for `Literal` and `items` for `list[int]`-style hints, skips var parameters and falls back to a string per parameter instead of losing them. `LangChainAdapter` handlers with `**kwargs` nested the extras under the parameter name instead of passing them as keywords.

**What remains.**

- **The CrewAI adapter has never run against real `crewai`.** The tests use a fake `BaseTool` (pydantic model, `name`/`description`/`args_schema`, abstract `_run`, optional `_arun`, `run`/`arun`). Two real-package tests exist and are skipped when `crewai` is missing. Expect to adjust on first run: newer crewai versions rewrite `description` and validate arguments in a wrapper the fake does not have. Reason: crewai is heavy, and installing it was out of scope.
- **No hosted model has driven any adapter.** The Anthropic block shapes come from the public documentation, not from a live response; LangChain and LangGraph were run with scripted fake chat models. Reason: no keys, no spending in tests. What a real model does with these tools, including how often it emits arguments the schema rejects, is unmeasured.
- **LangGraph and LangChain are verified at one version each** (`langgraph` 1.1.6, `langgraph-prebuilt` 1.0.9, `langchain-core` 1.2.26, `langchain` 1.2.15, on the implementer's machine). Nothing was run at the `langchain-core>=1.3.3` floor the existing `langchain` extra declares (that machine had 1.2.26).
- **`pyproject.toml` has no `langgraph` or `crewai` extra.** Proposed, not added: `langgraph = ["langgraph>=1.1.6", "langchain-core>=1.3.3"]` (floors are the installed versions that were verified, not the lowest that would work; older releases were not tried) and `crewai = ["crewai"]` (no floor verified; add one after the two skipped real-package tests have run). The tests for both skip with a reason when the package is missing, so the gate does not run them unless the package is installed; adding `langgraph` to `dev` would change that. Anthropic and OpenAI need no dependency.
- **Tools are not filtered per agent.** Every registered tool is offered to every agent; the gate refuses at call time. Reason: `Tool` carries no per-agent visibility, and inventing one is a policy change.
- **The JSON Schema is shallow.** Scalars, `Optional`, `Literal`, `dict` and `list`/`tuple`/`set` of a scalar. Pydantic models, several-type unions and nested structures are described as `string`, and the handler receives what the model sent. Reason: the schema is deliberately stdlib-only.
- **A catch-all `ToolNode(handle_tool_errors=True)` swallows `UnknownAgentError`** into a tool message. The adapter cannot prevent it, since the node is the caller's; documented in `docs/adapters.md`.
- **Arguments a handler cannot bind** are answered before the gate by the LangChain, LangGraph and CrewAI adapters, but the OpenAI and Anthropic adapters pass them on, so the gate allows the call and the handler's `TypeError` is recorded as a failure. Both are safe (the handler does not run); they differ in what is on the chain.
- **Anthropic streaming and `server_tool_use` results** are not handled: only complete `tool_use` blocks are answered, and server-side tool blocks are skipped.
- **Handlers with `*args`** cannot be called through any adapter (the gateway calls `handler(**arguments)`); extra positionals are refused with `Action failed:`.

### SDK export and verification: built for the SDK session, not for `serve`

**Status: built (2026-09-30).** This closes the "Persistence" item under "Developer SDK" and the entry "An SDK session cannot be verified from the CLI".

- `CausalMesh.export(directory)` writes `run.json` (the signed `chain`, `arm`, `run_id`, `head_hash`, plus an unsigned `envelope`) and `keyring.json` (public keys only; a test checks that no seed or private key appears in either file). `causalmesh verify --run <directory>` reads it with no change to its input format.
- `causalmesh verify` now prefers a `keyring.json` beside `run.json` to the public keys embedded in the records; with the file absent the old behaviour is unchanged. A `keyring.json` that is present but unreadable or malformed **fails** the run instead of falling back, because the fallback is the weaker check. The result reports which source was used (`keys`: `keyring.json` or `embedded`).
- Tests run the real verifier through the CLI: a clean export verifies; a changed event and a dropped event fail; a chain re-signed under a foreign seed (a second session making the same calls) **fails against the keyring**. The same forged chain with `keyring.json` deleted still **passes**, and a test pins that as the known limit rather than hiding it. Reverting the CLI change makes the foreign-key tests fail.
- `export` refuses to write over an existing `run.json` (raw evidence is written once, as the scheduler does) and over a `keyring.json` with different keys.
- Opt-in `persist_to=<dir>`: the relay appends `chain.jsonl` as it goes (flushed per event, the existing `ChainStore`) and `keyring.json` is written at construction. It refuses a directory that already holds a chain. `CausalMesh.close()` closes the file.

**What remains.**

- **The keyring is only as good as its channel.** `keyring.json` sits beside the run it vouches for, so whoever can replace `run.json` and `keyring.json` together can forge both. It protects against a chain re-signed by someone who does not control the keyring, which is the auditor who is handed the ring separately or pins `key_ring_fingerprint`. Nothing pins the fingerprint automatically, and `verify` has no `--keyring` option to supply a ring from elsewhere. Not built. This is the narrowed form of "`causalmesh verify` trusts the keys inside the artifact" below.
- **A crash leaves `chain.jsonl` and `keyring.json`, not `run.json`.** `verify --run` reads only `run.json`, so a persisted-but-never-exported session cannot be verified by the CLI. There is no `recover` or export-from-chain command.
- `export` is a snapshot of the in-memory relay, and its envelope's per-event wall times are in memory only: a session reopened from `chain.jsonl` has none (they are `unknown`, absent from the map, not zero).
- `serve` has no export endpoint or shutdown hook that calls `export`; its evidence is still gone when the process stops.
- No `--keyring` or fingerprint check exists for experiment runs (`--id`, `--all`); those still use embedded keys unless a `keyring.json` was placed beside a run by hand.

### A logical clock in the signed chain: built for the gateway, not the chat path

**Status: built for `ToolGateway`, so for the SDK and for `serve`'s `/execute` (2026-09-30); the chat path followed on 2026-10-12 (see "The chat path signed the wall clock").** This closes the "Wall-clock timestamps in the signed chain" item under "Developer SDK".

- `ToolGateway` stamps each call with a per-session `LogicalClock`: `base_us + n * tick_us`, constant defaults (`0` and `1_000_000`), overridable as `clock_base_us`/`clock_tick_us` on `CausalMesh`, `from_config` and `ToolGateway`. That one value is the signed `timestamp_us`, the time the gate is asked about and the ledger row's `timestamp_us`, so a verdict, a ledger row and an event describe one moment and carry the same number.
- The wall-clock time of each call is kept in `ToolGateway.wall_times()` (event id to microseconds) and written to `run.json`'s unsigned `envelope.wall_time_us_by_event`, with the export time and the clock parameters. It never reaches the chain.
- Two sessions with the same seed and the same call sequence have the same head hash (tested for the SDK, for the async path and for two `serve` apps driven over `/v1/tools/{name}/execute`). A different sequence gives a different head.
- A caller-supplied `now_us` is still signed as given, and the clock moves past it so later calls never go backwards behind it.

**What it changes, stated rather than hidden.**

- **Time in a session is call count.** A lease or window of N seconds lasts N calls at the default tick, however long they take. That suits replay and is wrong for anything meant to measure real elapsed time. Nothing in the SDK measures real elapsed time today: the ledger's totals are over the run and ignore the timestamp (it is used for ordering).
- **Leases must be granted on this clock.** `CausalMesh.now_us` is the moment to acquire at. A test wires a `ClaimRegistry` into a `ToolGateway` by hand and pins both halves: a lease granted at `now_us` blocks and then expires after the stated number of calls, and a lease granted on the wall clock is never seen to expire (the gate's clock never reaches it). `mesh.claim()` and `mesh.release()` now default to this clock; see the entry below.
- Timestamps are not dates. An auditor reading `timestamp_us: 0` must not read 1970; the envelope's `clock.kind` says `logical`.
- The clock is thread-safe, but a timestamp is issued before the call runs, so concurrent callers can be signed out of chain order. The verifier checks no timestamp ordering, and `serve` serialises executions under a lock.
- The harness (`tasks/runner.py`, the scheduler) has its own clock and was not touched.

### SDK claims and a human checkpoint handler (2026-09-30)

**Status: built, opt-in.** This closes the "Claims" and "Human-in-the-loop approval" items under "Developer SDK" and replaces the last paragraph of "Checkpoints and identity" ("What this does not do").

**Claims.** `CausalMesh(claims=ClaimRegistry(...))` (and `from_config(..., claims=...)`) hands the registry to `ContractGate.build`. That is the whole of enforcement: `Gate._rule_claim` already asked `registry.may_write` and `ContractGate.check` already called `record_denial` on a `claim` refusal; there is no second gate and no claim logic in the SDK. The lease run id and the gate run id are both `mesh.run_id` (`"sdk"` by default), so a lease protects exactly what the gate consults. Leases are taken explicitly: `mesh.claim(agent_id=, path=, duration_us=, now_us=)` returns the registry's `ClaimOutcome` as data (granted, or refused with the `holder`), `mesh.release(claim_id=, ...)` likewise, `mesh.denials()` reads the registry's denials for this run, and `mesh.claim_registry` exposes the registry. `path` may also be a `Resource`; the lease key is `Resource.path(path).identity` (for example `path:src/a.py`), so `src\a.py`, `./src/../src/a.py` and `src/a.py` are one lease.

**Default off, and shadow on C0 to C2.** With `claims=None` the gate is built with `registry=None` and behaviour is identical to before. `ContractGate.build` keeps the registry for its own refusal recording only when enforcing, but passes it to the policy gate always, so on C0-C2 the claim rule runs as a shadow check: a contested call executes and the result carries `would_refuse`, `shadow_rule="claim"` and `shadow_reason`, and the signed event records `would_refuse`. No denial row is written on an unenforced arm, because nothing was blocked (a contested `mesh.claim()` is an exception on any arm: `ClaimRegistry.acquire` writes its own denial, as it always has).

**A choice stated: no acquire-on-first-mutating-call.** Considered and not built, for three reasons. (1) A contested implicit acquire would write a denial in `acquire` and the gate would write another for the same blocked attempt, doubling the enforcement count, the class of defect `record_denial`'s docstring records. (2) An implicit lease is never released unless something says when, so the first agent to touch a path would lock it out until expiry without anyone having decided that. (3) It needs the resolved paths before the gate runs, which means reaching into `ToolGateway.execute`, a file other work was editing. A lease is a statement an agent or operator makes; making it explicit keeps it that. If wanted, the safe form is an explicit `auto_claim_us=` on `CausalMesh` that acquires in `ToolGateway.execute` before the gate and skips `record_denial` for a refusal its own acquire already wrote.

**Human checkpoint handler.** `TerminalCheckpointHandler` (`src/causalmesh/policy/terminal_handler.py`, exported from `causalmesh.policy`) satisfies the existing `CheckpointHandler` protocol, so the gate is unchanged. It refuses on every failure and approves only on an explicit `y`/`yes`: injectable `input_stream`/`output_stream` (defaults `sys.stdin`, `sys.stderr`, so `--json` stdout is not mixed with prompts); `require_tty=True` refuses without asking when input is not a terminal; end of input, a closed or raising stream, an unwritable output and a timeout (`timeout_s`, default 120, per checkpoint) all refuse, with the read on a daemon thread so the caller waits with a deadline; a line typed after its question timed out is discarded, never taken as the answer to the next question; unintelligible answers are re-asked `max_attempts` (default 3) times, then refused; output is printable ASCII, with control characters, ANSI escapes, newlines and non-ASCII in agent-controlled names shown as `\xNN`/`\uNNNN`, backslashes doubled and long values truncated with their length stated; a lock serialises prompts across threads; and `decisions()` is its own log (agent, resource, checkpoint, approved, reason, outcome of `answered|eof|timeout|no_tty|no_output|invalid`, `now_us` as passed to the gate), outside the signed chain.

`CausalMesh(checkpoint_handler=...)` and `from_config(checkpoint_handler=...)` forward a handler to `ContractGate.build`. `causalmesh experiment run --checkpoint-prompt` installs the handler only when a contract was found, the contract declares `policy.checkpoints` and stdin is an interactive terminal; otherwise it says so on stderr and `AutoDenyHandler` stays. The scheduler keeps a handler object out of the run artifact's `provenance` (it is not data; its class name is recorded instead), sets `reproducible: false` when the handler declares `deterministic = False`, and adds a `checkpoint_decisions` list (the handler's log for that run) to the artifact envelope. A run without a handler serialises exactly as before.

**A defect found on the way.** `policy.checkpoints: [{on: path, ...}]` written in a YAML file did not load: YAML 1.1 reads an unquoted `on` as the boolean `True`, so the entry arrived as `{True: "path"}` and the parser raised a `TypeError` (from sorting the unknown key names) instead of a `ContractError`. No test loaded a checkpoint from YAML. `_parse_checkpoint` now reads the `True` key as `on`, and `_reject_unknown` no longer assumes string keys. Pinned in `tests/sdk/test_checkpoints.py`.

**What the chain records (unchanged, stated).** The runner (`tasks/runner.py`) writes `CHECKPOINT_DECIDED` only for checkpoint verdicts that refused, under the `checkpoint` identity, whose key is derived only when `contract.checkpoints` is non-empty. The SDK records a refused checkpoint as the call's `FAILURE` event, with `rule: "checkpoint"` and the handler's reason in the payload, and no `CHECKPOINT_DECIDED` event. Approved checkpoints leave no chain record in either path; a test pins that so a change is deliberate.

**Tested.** `tests/sdk/test_claims.py` (off by default; two agents on one path; C0-C2 report `would_refuse` with no denial; lease and gate share the run id; outcomes as data; misuse raises; mutation-checked: `registry=None` in `_build_runtime` fails 13 of them), `tests/sdk/test_checkpoints.py`, `tests/unit/test_terminal_checkpoint.py` (timeout and the stale-line rule mutation-checked), `tests/adversarial/test_terminal_checkpoint_escape.py` (ANSI, CR, forged lines, backspace, bidi override, emoji, NUL, huge names) and `tests/integration/test_checkpoint_prompt.py` (the CLI flag only acts on an interactive stdin; a real smoke collection with the handler writes a serialisable artifact, `reproducible: false`, per-run decisions that sum to the handler's log, and `CHECKPOINT_DECIDED` on the C3 chain). The contended-path tests use scripted calls and the checkpoint tests use scripted answers; nothing here says anything about agent behaviour.

**Not built, recorded with reasons:**

- **Approved checkpoints are not on the chain, in either path.** A person's yes is the thing an auditor would most want to see signed, and it is the one decision not recorded. Recording it means a `checkpoint` key in the SDK relay (derived only when checkpoints are declared, as the runner does), a reservation of that agent id so `execute(agent_id="checkpoint")` cannot forge the identity (`mesh.agents` would otherwise list it as a callable agent), and a decision on whether the runner records approvals too. The reason text must stay free of clock and host to be reproducible, which the terminal handler's is. Not cheap enough to do beside a change to `ToolGateway`, so not done. Runner and SDK therefore still differ here.
- **`checkpoint_decisions` is an envelope, not evidence.** The handler's own log is outside the signature, so it can be edited after the fact. The signed record of a refusal is the chain's; of an approval, there is none.
- **Checkpoints are consulted on every arm.** `Gate.check` runs checkpoints whether or not it enforces, so `--checkpoint-prompt` asks a person on C0-C2 too, where a "no" only becomes `would_refuse`. The CLI says so when it installs the handler. A scripted or arm-aware handler is the way around it; the handler does not know the arm.
- **The prompt blocks the calling thread.** The protocol is synchronous. From `execute_async` it blocks the event loop until the person answers or `timeout_s` passes, and concurrent agents wait in line behind the lock. The timeout is per checkpoint and counted from when the question is shown.
- **A daemon reader thread can be left blocked on stdin** after a timeout. It reads at most one line and that line is discarded. CPython can print a "could not acquire lock ... at interpreter shutdown" message if the process exits while a daemon thread is inside a blocking stdin read; not observed in the tests, which use injected streams.
- **Real terminals were not driven.** `require_tty`, Windows consoles and a live TTY were tested only with injected streams. The output is ASCII on purpose so cp1252 cannot raise; that has not been run on Windows.
- **A run that uses the handler is not reproducible from the seed.** It says so (`reproducible: false`); the answers are a person's.
- **Claim expiry uses the caller's clock, and the default is the wall clock.** See the next entry. Leases are not in the signed chain (the registry is outside it), so this does not touch chain reproducibility. The default claim id is `<run_id>_<agent_id>_<n>` from a per-session counter: two sessions sharing a registry and a run id can collide (`ClaimError`); give them different run ids or pass `claim_id=`.

### `mesh.claim()` defaulted to the wall clock while the gate read a logical one

**Status: fixed.** `claim()` and `release()` now default `now_us` to `mesh.now_us`, the logical time the gate reads, so a lease lasts `duration_us` of it and then expires. `tests/sdk/test_claims.py::TestTheDefaultClockIsTheSessionsLogicalClock` takes a lease with no `now_us` and sees the holder block a second agent and then release it; reverting the default makes it fail. A caller who passes a wall-clock `now_us` to `execute()` must still pass the same clock to `claim()`. What follows is the original finding. The SDK claims work and the logical-clock work landed separately and each note is right about its own half. `mesh.claim()` and `mesh.release()` default `now_us` to `utc_now_micros()` (`sdk/mesh.py`), while `ToolGateway` asks the gate about a per-session logical clock that starts at `clock_base_us` (0). The registry's liveness test is only `now_us < expires_at_us`, so a lease granted with the default `now_us` expires at roughly the wall clock plus its duration, a moment the logical clock never reaches: it blocks every other agent for the life of the session and never expires as the gate sees it. That fails closed, but it is not what `duration_us` says. `tests/sdk/test_clock.py::test_a_lease_granted_on_the_wall_clock_never_expires_in_logical_time` pins the hazard with a registry wired in by hand; every `mesh.claim()` call in `tests/sdk/test_claims.py` passes an explicit `now_us`, so no test exercises the default. **What it took:** defaulting `now_us` to `mesh.now_us` in `claim()` and `release()`.

### The chat path signed the wall clock

**Status: fixed (2026-10-12).** `/v1/chat/completions` still does not go through `ToolGateway.execute` (it calls `m._gate.policy.check` and `m._relay.ingest` itself, `server/app.py`), but it now takes its timestamp from the gateway's logical clock (`ToolGateway._stamp`, the clock `/execute` uses), so the verdict, the signed `timestamp_us` and the event describe one logical moment. The event id is drawn from the gateway's own counter (`reserve_event_id`, `sdk_<agent>_<n>`) instead of `serve-<agent>-<wall us>-<n>`, so it is reproducible, cannot collide with a tool call's id and continues numbering on a resumed chain. The wall time of each chat call is recorded in `ToolGateway.wall_times()`, which the export writes to the unsigned `envelope.wall_time_us_by_event`. `tests/server/test_chat_reproducible.py` (marked `reproducibility`): two identical chat sessions (same seed, contract, requests; allowed and refused) have equal signed records and head hash, and no signed timestamp is a wall time; reintroducing `time.time_ns()` for the timestamp fails all three tests that cover it. `tests/server/test_logical_clock.py` now pins the fix rather than the gap.

**What is still not covered.**

- **Chat events share the tool-call counter, so ids in a mixed session shifted.** A tool call made after a chat call now gets the next `sdk_<agent>_<n>`, not `n` counted over tool calls only. Sessions that mixed both were never reproducible before, so no reproducible hash changed; chat-only and tool-only sessions are numbered as a tool-only session always was.
- **Not a date, and call count, not elapsed time.** The same limits as the logical clock entry above: a chat event's `timestamp_us` of `0` or `1000000` is a position in the session, and a window or lease measured in seconds lasts that many calls.
- **Out-of-order stamps are possible and unverified.** The stamp is issued under `serve`'s lock, so chat and `/execute` serialise; a caller driving the mesh from other threads while serving can still be signed out of chain order, as for any gateway call. The verifier checks no timestamp ordering.
- **The unsigned wall times are in memory only.** `serve` has no export endpoint (see "Developer SDK"), so `wall_times()` is reachable from the process, not from the wire.
- **The chat path still bypasses `ToolGateway.execute`, and reaches into its privates** (`_stamp`, `_wall_times`) rather than a public method. A chat call writes no ledger row and does not go through the boundary's hooks; unchanged and not part of this fix.
- **Other wall-clock uses in `server/` are unrelated to the chain:** credential expiry and request timing (`credentials.py`, `observability.py`) read the wall clock on purpose and are not signed. Not audited again beyond a grep for `time.time`/`datetime` in `server/`.
- **Verified here by `tests/server` only** (and the reproducibility marker); the full suite was not run in this change.

## CI was removed (2026-09-30)

**Status: removed by decision (commit `2b88814`).** GitHub Actions had not
started a job since 2026-09-28: every run failed before its first step with
*"The job was not started because recent account payments have failed or your
spending limit needs to be increased."* The owner removed the workflow instead
of paying for hosted runners. `python scripts/check.py` is the gate now: lint,
format, mypy on the enforced modules, bandit and the full suite.

**What that no longer covers, stated rather than hidden.**

- **Remote execution.** No result is corroborated by a second machine. The
  numbers in the README are from one Windows 11, Python 3.12 machine.
- **The platform matrix.** The workflow ran Linux, Windows and macOS on Python
  3.11 and 3.13. The gate tests only the machine it runs on, so the claim in
  `pyproject.toml` (3.11 to 3.13, three platforms) is untested apart from the
  Windows 3.12 runs recorded here.
- **`pip-audit`.** Not in the gate, because it needs the network and a clean
  environment. `pip-audit .` reported no known vulnerabilities in the project's
  own dependencies on 2026-09-30, and a fresh resolve of the runtime plus the
  `server` extra was also clean. The audit machine's older environment was not:
  it held starlette 1.0.0, cryptography 46.0.7, anyio 4.13.0 and click 8.3.2,
  each with advisories fixed in later releases. The floors in `pyproject.toml`
  (for example `cryptography>=41.0`) sit well below those fixes, so an
  environment held at old versions is not protected by them. Not changed.
- **The site build.** Not in the gate. `npm run types:check && npm run build`
  passed in a Linux Node 22 container on 2026-09-30. On the Windows audit
  machine `next build` fails because Windows Application Control blocks the
  unsigned `yuku-analyzer` native binding; that is the machine's policy, not
  the repository.
- **The evidence job.** The workflow produced a smoke collection and verified
  it. The suite covers the substance (`tests/integration/test_cleanroom_verification.py`,
  the manifest and audit tests in `test_cli.py`), and the same flow was run by
  hand on 2026-09-30, including a tampered signed event being rejected. It is
  not one command any more.

## Product-readiness audit (2026-09-30)

Found by auditing the tree against its own claims, not by a failing test.
What was fixed is in `CHANGELOG.md` (async unknown-agent bypass, chat-completions
agent and body handling, upstream scheme and host, `create_app` fail-open,
OpenAI adapter error translation). These are the gaps that remain, and why.

### Identity on the HTTP surface: bound tokens and their lifecycle built, proof not

**Status: partly built (2026-09-30).** A bearer token authenticates the client. `--agent-token AGENT=TOKEN` (or `create_app(agent_tokens=...)`) binds a token to one agent: the server takes the agent from the token and refuses a request that names another (403). An unbound `--api-token` is still the operator's, and still asserts. Chat and `/execute` events record `identity_source` (`token-bound` or `asserted`), and a call made directly through the SDK carries none (`tests/server/test_identity_source_on_tools.py`), so the chain can tell a credential from a claim. A token is compared in constant time. Expiry, revocation and rotation are built; see the next entry.

**What remains.** Tokens are shared secrets. They travel over plain HTTP unless the operator turns on TLS or puts a proxy in front (see "HTTP hardening"), and even over TLS they prove nothing to anyone who did not see the request. The server holds every agent's signing key, so a signature attests that the server recorded an event, not that the agent did. **What it would take:** per-agent signing keys held by the agents (so a signature is theirs), or mutual TLS; either is a protocol decision this project has not made.

### Token lifecycle: expiry, revocation, rotation built; proof still not

**Status: built (2026-09-30).** A token can expire, be revoked and be rotated without restarting `serve`, and the chain says which credential acted.

- **Expiry.** `--agent-token AGENT=TOKEN@EXPIRY` (ISO 8601 such as `2026-12-31T00:00:00Z`, or unix seconds), `--api-token-expires`, or `expires:` in the tokens file. A credential is valid while `now < expires_at`: at the expiry instant it is already refused. Past it, the request gets 401 "Token expired". Expiry is judged on every request, so nothing outlives it, including a set kept after a failed reload. Times without a zone are UTC. The clock is injectable (`create_app(clock=...)`).
- **Tokens file.** `--tokens-file PATH` (also `CAUSALMESH_TOKENS_FILE`), YAML or JSON: `tokens:` is a list of `{id, token, agent?, expires?}`. It is re-read when its mtime, size or inode changes (one `stat` per request), and on SIGHUP on POSIX. Deleting an entry makes that token fail on the next request; adding one takes effect on the next. Flag tokens stay valid beside the file.
- **Rotation.** Several entries may name one agent. Add the new token, move the clients, delete the old entry: both are valid in between. More than two live tokens for one agent logs a warning.
- **A bad reload keeps the last good set.** Malformed YAML, a missing or unreadable file, a bad entry, a duplicate label or token, an agent with no key in this session, or a permissive mode all leave the credentials as they were, and log one warning per distinct failure that carries no file content and no token. Failing closed would lock every client out over a typo; failing open is never acceptable, and keeping the old set is neither. Its cost: a token the operator meant to revoke in that same broken edit stays valid until the file is fixed or the token expires. To revoke everything on purpose write `tokens: []`. A bad file at start-up is an error: there is no good set to keep.
- **Permissions.** On POSIX a tokens file with any group or other bit set is refused, at start-up and on reload, with the `chmod 600` to run. On Windows mode bits mean nothing, so nothing is checked; restrict the file with an ACL.
- **Record.** Chat and `/execute` events carry `credential_id` beside `identity_source`: the operator's label for the credential (`id:` in the file; `agent-token:AGENT` and `api-token` for plain flags). It is signed and reproducible, because it comes from configuration and not from the secret, a clock or a random id, and it is never the token or a digest of it (a digest of a guessable token could be tested offline). Labels are limited to `[A-Za-z0-9._:-]`, 64 characters, and a label that contains its own token is refused. With authentication off the field is absent, not `none`.
- **Logs.** No token is logged. Reload and refusal messages name labels, counts and line numbers. The log redactor (`RedactingFormatter`) accepts a callable, and `serve` hands it the credential store, so a token added by a reload is scrubbed from the next line and a revoked one stays scrubbed.

Code: `server/credentials.py` (`Credential`, `CredentialStore`, `parse_expiry`, `split_token_expiry`, the file parser), `server/auth.py`, `server/app.py`, `server/observability.py`, `cli/commands_serve.py`. Tests: `tests/server/test_token_lifecycle.py` and `tests/integration/test_serve_tokens.py` cover the expiry boundary (valid one millisecond before, refused at the instant), revocation, addition and rotation overlap, SIGHUP, a bad reload keeping the last good set (parametrised over thirteen malformed and invalid files, each asserting nothing leaked to the log), permissive modes, the constant-time compare (every credential compared, expired ones too, no early exit), no secret in logs, errors or the chain, and `credential_id` on chat, `/execute` and denied calls. Mutation-checked: an early `break` in the compare loop, `>` for `>=` at the expiry, and a reload that swallows a parse error each fail the suite.

**What remains.**

- Tokens are still shared secrets, and the server still holds every agent's signing key. Expiry and revocation shrink the window in which a leaked token is useful; they do not make a token prove anything to someone who did not see the request. Per-agent signing keys held by the agents, or mutual TLS, are still undecided protocol questions.
- Revocation is per process and needs the file to be reachable. There is no admin endpoint and no shared revocation list, so several processes must all read the same file.
- A detected edit within the timestamp granularity relies on a byte compare for two seconds after each read. A file changed in place, to the same size, with the old mtime restored, more than two seconds after it was read, is not seen until SIGHUP (POSIX) or the next change. There is no SIGHUP equivalent on Windows.
- SIGHUP reloads only when `--tokens-file` is set; otherwise the default action (terminate) is untouched. With a file set, a terminal hang-up reloads instead of stopping the process.
- A keep-last-good set is silent to clients. There is no metric or health signal that the file is currently unreadable, only the log warning; `/health` and `/readyz` are unauthenticated and deliberately say nothing about it.
- A token containing `@` followed by something that looks like a date cannot be given as `--agent-token` (it would be read as an expiry). Put it in the file.
- The rate-limit table is keyed on a digest of each token that authenticated and is never pruned, so a long-lived process that rotates many tokens grows it a little per rotation.
- The redactor works by value, so a token shorter than four characters is not scrubbed (as before); `serve` warns under 16.

### `causalmesh serve --tools`: operator code loaded at startup (built, with limits)

**Status: built (2026-09-30).** This replaces "`causalmesh serve` registers no tools", which stood until now: the command built a `CausalMesh` and never called `register_tool`, so `/v1/tools` was empty and `/v1/tools/{name}/execute` answered 404 for every name, in the Docker image too. `--tools MODULE:FUNC` or `--tools FILE.py:FUNC` (repeatable) now imports the named code and calls `FUNC(mesh)` once, before the first request; `FUNC` registers tools with `mesh.register_tool(Tool(...))` (`src/causalmesh/server/tools.py`). The split is on the last colon, so a Windows drive letter stays in the path.

**What it does, stated plainly.** `--tools` imports and runs code with the server's own privileges. That is the whole feature, and it is why the answer to the old question (importing arbitrary callables from a config file) was not to read the contract:

- The spec is the operator's, typed on the command line or set in the service definition. It is never taken from the contract, a request, a header or anything a client sends. The `tools:` section of `causalmesh.yaml` names tools; it does not name code, and nothing reads it as an import (`tests/integration/test_serve_tools.py::TestToolsAreNeverDerivedFromTheContractOrARequest`).
- Every tool it registers is still called through the gateway: the contract gate decides and the evidence is recorded. Loading a tool grants nothing.
- Anyone who can change the spec or the file it points at can run code as the server, exactly as anyone who can edit the service's command line can. Treat it like any other code you deploy.

A bad spec is a usage error that stops startup with the reason and exit 2: a malformed spec, a module or file that cannot be imported, a missing or non-callable function, an `async` function, a function that does not accept one argument, a function that raises, a function that registers nothing, and a tool name registered twice (two files of the same name do not shadow each other).

**Limits, stated rather than hidden:**

- Tools are registered at startup only. There is no reload and no way to add or remove one while the server runs; changing the set is a restart.
- The module form needs the module on `PYTHONPATH`, not merely in the current directory; use the file form for a file.
- Nothing sandboxes the code or the tools it registers. The Docker image is not a sandbox either (`docs/security.md`).
- Executions stay serial under one lock (see "HTTP hardening"), so a slow registered tool holds up every other call.
- Covered by `tests/integration/test_serve_tools.py` (a real server process driven over HTTP) and `tests/server/test_tools.py`. No real agent or model has called these tools.

### Non-path resources through the SDK: built, with these limits

**Status: built (2026-09-30).** `Tool(resource_kind="endpoint"|"spend"|"budget",
amount_arg=...)` hands the gate every kind the policy layer supports, with URL host
extraction, strict argument types and a per-call amount. Paths are decided on the
canonical file (`..`, `./`, case, a trailing dot or space, an absolute spelling
inside the contract's directory). A declared total needs a ledger
(`CausalMesh(ledger=...)`), and a total with no ledger is refused, since nothing
could enforce it. The total is reserved before the handler runs and settled after it
(see the next entry); it used to be checked and then recorded, and was racy.

**Limits, stated rather than hidden:**

- A tool that declares no resource is checked against nothing and runs (the
  contract states exceptions), and `mutating=False` skips the gate for every kind,
  so a read-only tool that reaches a network is not held to an allowlist.
- Totals are reserved, not checked-then-recorded, and a raising handler's amount is
  released unless the tool says otherwise; both limits this list used to carry are
  replaced by the next entry, which states what remains.
- A budget name nobody declared is unlimited: absent means unrestricted, so a
  misspelt name is too. Keep the name in the tool, not in the model's arguments.
- Case is folded for ownership, so on a case-sensitive filesystem `Docs/` and
  `docs/` share an owner (fail closed). Symlinks are invisible to a lexical check.
- An absolute path outside the contract's directory is not this contract's to
  decide, and is not refused.

### Totals are reserved, then committed: built, with these limits

**Status: built (2026-09-30).** This replaces two limits that "Non-path resources through the SDK" listed: that totals were check-then-record, and that a raising handler was never counted. A declared total (`usd_total`, `tokens`, ...) is now **reserved** before the handler runs and settled after it.

**What was built.**

- `Ledger.reserve` sums recorded consumption plus live holds, compares the result with the limit and inserts the hold in one `BEGIN IMMEDIATE` transaction, so callers racing on one allowance are admitted one at a time against the true remainder, across threads and across processes. A refusal is returned as data (`ReserveOutcome`, with the `spent` and `held` the transaction saw). `commit` turns a hold into an entry and `release` drops it; each is a single transaction. The holds live in a `reservation` table created on open, so an existing ledger file needs no migration. `Ledger.total` is unchanged (recorded consumption only); `held` and `release_all` are new.
- `Gate.check(..., holds=[])` takes the reservation inside the budget rule and appends it to `holds`. A refusal anywhere in the same check, and any refusal of a later resource in the same call, releases what that call had taken, so a refused call holds nothing. Without `holds`, `check` is still a read-only question, but it now counts live holds as well as recorded spend.
- `ToolGateway` reserves through the gate, then commits when the handler returns, releases when it raises, and releases on an interrupt or cancellation (which propagates). `GatewayResult`, `Ledger.record` and the ledger's `entries` are unchanged. The gateway also serialises event emission (the id counter and the relay), which the first concurrent callers showed was not safe; the handler and the reservation run concurrently. `serve` still executes serially.
- **A raising handler is released by default, and a tool can say otherwise.** `Tool(..., spend_on_error=True)` counts the amount as spent when the handler raises, for a tool that cannot tell whether the money left. The default under-counts (a failure before the money moved is not charged); the opt-in over-counts (a failure that never spent is). Neither is right for every tool, which is why it is the tool's declaration and not the gateway's guess. The result is still a failure either way.

**Tested (`tests/gateway/test_atomic_totals.py`; numbers recorded by the implementer).** 120 threads against a 50-call total: exactly 50 run, 70 are refused on `budget`, the handler runs 50 times, the recorded total is exactly 5.00 and no hold is left. A watcher thread asserts recorded plus held never exceeds the cap mid-race. Four spawned processes on one ledger file are granted exactly 50 holds between them. Reverting the reservation in the gate (back to check-then-record) lets all 120 run and fails the race tests; changing `BEGIN IMMEDIATE` to a deferred `BEGIN` fails them too.

**Limits that remain, stated rather than hidden:**

- A holder that dies between reserve and settle leaves its hold behind. That over-counts, which fails closed, until an operator runs `Ledger.release_all` (safe only when nothing in the run is executing). There is no expiry, because any timeout shorter than the slowest handler would release money that is still in flight. No CLI command exposes `release_all` yet.
- A hold whose `commit` fails (a ledger that cannot be written) stays counted and is reported on `result.audit_error`; the call's outcome stands.
- The reservation exists only on the SDK path. Callers that use `Gate.check` directly (`causalmesh policy check`, the x402 adapter, `serve`'s upstream check) still ask a question and record afterwards; they see in-flight holds but do not take one. The x402 adapter's check-then-pay is therefore still racy for a caller that pays outside the gateway.
- Interrupt and cancellation release the hold even if the money had already left; `spend_on_error` covers exceptions only.
- The unenforced arms (C0 to C2) take the hold whatever the total, so they record what they spend; the refusal they would have made is reported as before.
- Concurrency stops at the ledger and the emit lock: `ContractGate.verdicts` is a shared list, so the "would have refused" report on a result can name a concurrent call's verdict under C0 to C2. Enforced arms do not read it.
- A reservation is taken per resource, in call order. A call that declares the same destination twice reserves twice, as it records twice.
- Serial `serve` bounds throughput at one call at a time; nothing here changes that, since the gateway's handler concurrency is only reachable to a library caller.

### HTTP hardening: what is built, what is not

**Built (2026-09-30):** the container runs as non-root and declares a
`HEALTHCHECK`; `/docs`, `/redoc` and `/openapi.json` exist only in dev mode; request
bodies over 1 MiB are refused (413, also for chunked bodies); an opt-in per-credential
rate limit (`--rate-limit`, 429 with `Retry-After`); sync handlers and the upstream
call run off the event loop, with one lock keeping executions serial so the chain
stays in one order; `/execute` returns the handler's plain-JSON value; a handler's
exception text and the list of known agents no longer reach clients; upstream
redirects are refused so the upstream key cannot be sent to another host; an
allowed chat call that could not be recorded is not forwarded.

**Also built (2026-09-30), replacing "TLS is not built":**

- **TLS.** `--ssl-certfile` and `--ssl-keyfile` (or `CAUSALMESH_SSL_CERTFILE` and `CAUSALMESH_SSL_KEYFILE`) serve HTTPS. Both or neither; both must exist, be readable and load together, which is checked before the socket opens (`server/tls.py`), so a mismatched key, a non-PEM file or a wrong passphrase is a usage error rather than a late uvicorn traceback. An encrypted key's passphrase is read only from `CAUSALMESH_SSL_KEYFILE_PASSWORD`, never from an argument (the process table, shell history and `docker inspect` would show it), it never prompts on a terminal, and the log redactor scrubs it. On a non-loopback host without TLS `serve` warns that bearer tokens cross the network in clear; `--require-tls` (or `CAUSALMESH_REQUIRE_TLS`) turns that warning into a refusal. Tested with a real certificate and a real HTTPS request, including that plain HTTP to the TLS port is not served and that a client which does not trust the certificate is refused (`tests/integration/test_serve_tls.py`).
- **Operability.** A request id on every response (`X-Request-ID`) and in every log line, an access log of method, path, status and duration (never the query string, headers or body) with every configured secret scrubbed by value, `/readyz` beside `/health` (503 when the session cannot take a gated call or the server is shutting down; unauthenticated and it names no agent, tool or count), `--log-level`, `--timeout-keep-alive`, `--timeout-graceful-shutdown`, and `--workers` greater than 1 refused with the reason (each worker would hold its own chain and rate limits). The request id is random and is never written to the signed chain.

**Not built:**

- TLS is opt-in: `serve` speaks plain HTTP unless given a certificate and key, and a non-loopback bind without them only warns unless `--require-tls` is set. There is no client-certificate verification (mutual TLS), no reload or rotation of the certificate without a restart, no TLS version or cipher setting beyond uvicorn's defaults, and no certificate issuance. The operator's proxy remains a fine place to terminate TLS.
- The rate limit is per process, opt-in, and counts only authenticated requests. A
  throttle on failed logins is deliberately absent: keyed on an address it lets one
  attacker lock out real users behind the same NAT. Use a long random token
  (`serve` warns under 16 characters) and a proxy for floods.
- Serial execution bounds throughput at one tool call at a time per server.
- A `causalmesh.yaml` bind-mounted into the container must be readable by uid 10001
  (mode 0644): a 0600 file owned by another uid looks like a missing contract.
- `HEALTHCHECK` assumes the default port 8420.

### The stdlib server was removed

**Status: removed 2026-09-30.** `adapters/serve.py`, the `http.server`
implementation of `serve`, was reached by nothing in `src/`, had no
authentication, derived the allowlisted host by string-splitting (the bypass
fixed in `server/app.py`) and answered an unreachable upstream with `200`.
Its tests went with it; `tests/integration/test_serve.py` now covers only the
command's own wiring, and the server is covered in `tests/server`.

### Windows path depth: fixed, one residual

**Status: fixed (2026-09-30).** The scheduler passed the runner a base that already
ended in the run id, so the id appeared twice in every workspace path
(`data/work/<experiment>/<run_id>/<run_id>/<agent>/...`). At a typical 48-character
checkout with a 29-character experiment id all four smoke runs failed, with
`FileNotFoundError` or a `shutil.Error`, not a message about length. The id now
appears once, and `check_path_budget` refuses, before anything is copied and in
plain words, a run whose deepest known path exceeds 259 characters. Verified at 48,
60 and 99 characters.

**Residual.** The check counts the workspace root plus the deepest fixture file, and
refuses only what is certain to fail. Something written below the fixture (a
`__pycache__` entry, a file an agent adds) can still overflow a checkout within a
few dozen characters of the limit, and would fail as it always did. A margin for it
was tried and refused checkouts whose runs all completed. Enabling Windows long
paths removes the limit.

**2026-10-12: the CooperBench base-repo cache hit the same limit, and a second bug hid
behind it.** On a Windows 11 / git 2.52 machine with `core.longpaths` unset, eight
tests failed on a clean HEAD: six in `TestFetchingBaseFiles` and two in
`TestThreeWayMerge`. Two causes, neither a test problem:

- *`Filename too long`.* `cooperbench_base._ensure_commit` names the cache repository
  after the whole upstream URL, so under a deep pytest temp directory the pack's
  `.git/objects/pack/pack-<sha>.promisor` exceeded 259 characters and `git fetch
  --filter=blob:none` died with `fatal: cannot write promisor file ... Filename too
  long`. The `UTF-8` assertion in `test_a_non_utf8_file_is_refused...` was a side effect
  of that fetch failure, not a second cause. Fixed: every git call in
  `cooperbench_base._git` runs with `-c core.longpaths=true`, and the one call that
  bypassed that helper (`cat-file --batch`, where a lazy blob fetch hit the same limit
  and surfaced as `missing`, an empty result) now goes through it. `cooperbench_batch.GitBaseResolver._git` had the same gap and got the same
  flag; its test (`test_cooperbench_batch.py::...test_reads_text_exactly...`) was *skipping* on this
  machine, and now runs.
- *Bare `bash` resolved to WSL.* `runner._run_integration_test` passed `bash` straight
  to `subprocess.run`. On Windows CreateProcess searches System32 before `PATH`, so it
  ran `C:\Windows\System32\bash.exe` (the WSL relay, exit 1 with no distro installed)
  although the preflight, using `shutil.which` on the harness `PATH`, had correctly
  found Git Bash. Every arm failed identically, which the gate reports as zero solved
  pairs: the `assert 0 == 1` in `TestThreeWayMerge`. Fixed: the executable is resolved
  on the harness's own `PATH` before it is run.

**Residual.** `core.longpaths` fixes git's side only. A cache or workspace path past
259 characters is still refused by anything else on the machine that lacks long-path
support (Windows Explorer, some editors, other tools) unless Windows long paths are
enabled. The cache directory name is still the full URL; a hash would shorten it, at the
cost of orphaning existing caches, and was not needed to make the tests pass.

### The Makefile's dead targets were removed

**Status: removed 2026-09-30.** `make report` and `make reproduce` called
`causalmesh report` and `causalmesh reproduce`, which do not exist (`report` is
listed as unbuilt in `frontend/content/docs/limitations.mdx`). `make typecheck`
still runs `mypy src`, which reports 14 errors in 11 files that predate the
audit; `make check` gates the enforced subset instead. `make` is not installed
on a stock Windows machine, which is why `scripts/check.py` exists.

### The pilot manifest named a person's host and username

**In the current tree: removed.** `data/manifests/pilot_landing.manifest.json` recorded
a contributor's hostname and OS username in its `environment` block
(`machine_id`, `operator_id`); both are now `"unknown"`, which is the value the
project uses for a field it does not have. No other tracked file carried either
(checked with `git grep`, case-insensitively). Editing the manifest does not affect
`causalmesh audit`: the manifest hashes the artifacts it lists, not itself, and no
document cites its own hash.

**In history: still present.** The original values are in three commits of that
one file: `54cd3f4`, `743a69e` and `9d258f6` (all 2026-09-15). No other file in any
commit contains them. A normal commit cannot remove them; only rewriting those
commits (`git filter-repo`) can, and that changes every later commit hash and
invalidates every clone and fork. That is a separate decision for the repository
owner and has not been made or attempted.

**The default that caused it: changed (2026-09-30).** `Environment.capture(root)` no longer records `platform.node()` or the OS username. By default `machine_id` and `operator_id` are each one of:

- `keyed:` plus 16 hex digits, the first 64 bits of an HMAC-SHA-256 over the value, keyed with a random 256-bit secret. The hostname and the username are derived under separate labels, so neither can be matched to the other.
- `unknown`, when no key can be kept (not a git checkout, the git directory is unwritable, the key file is malformed) or the value itself is absent. It is never a bare unsalted hash: a hostname or username comes from a small space and could be enumerated against one.

The secret is generated on first use at `<git-common-dir>/causalmesh/identity.key` (mode 0600, created with `O_EXCL`). It is inside `.git`, so it is never tracked or pushed, and every worktree of one clone shares it. No dependency was added. `Environment.capture(root, record_host=True)`, `causalmesh manifest write --record-host` and `causalmesh experiment run --record-host` record the real values; `manifest write` prints a note when it is used and its `--json` output carries `host_recorded`. `experiment run` was in scope too: it calls the same capture and copies both fields into each run's envelope.

Consumers checked: `provenance/manifest.py` (passes the flag through), `cli/commands_audit.py` (prints only the git commit, and echoes `manifest.environment` into the audit report, so it shows the digest or `unknown`), `cli/commands_experiment.py`, `tasks/runner.py` and `agents/base.py` (carry the two strings through untouched), `verify` and `doctor` (read neither field). Existing manifests are unchanged: `manifest.check` hashes the listed artifacts, not the manifest, and the tracked manifest already reads `unknown`. `causalmesh audit` could not be run against the pilot collection in the worktree this was built in, because `data/raw/` is untracked and absent there. Tests: `tests/unit/test_provenance.py::TestIdentityPrivacy` (sentinel host and user absent by default and present with the opt-in; the real hostname and username of the machine running the suite absent from a default manifest; the key stays in `.git` with mode 0600; no key or a corrupt key gives `unknown`) and `tests/integration/test_cli.py::TestManifestPrivacy` (the same through the CLI).

**What remains.**

- **History is untouched.** The original hostname and username are still in `54cd3f4`, `743a69e` and `9d258f6`. This change stops new publication and does nothing about those; rewriting them is still the repository owner's decision.
- **A digest compares only within one clone.** The same machine cloned twice has two keys and so two digests, and a fresh clone cannot reproduce an earlier digest. "Different digest" means "different machine or different clone", never "different person", and a digest is not evidence that two manifests came from one machine unless they came from one clone. Where that is not enough, there is no answer short of recording the real value.
- **Old manifests written with the real values stay as they are.** Nothing rewrites or scans for them. Anyone who used `--record-host` and committed the result has published the values again; the flag is a choice, not a safeguard.
- **`platform` and `python_version` are still recorded in the clear** ("Windows 11 (AMD64)", "3.13.5"). They describe a class of machine, not a person, and are what makes a run's conditions checkable, but a rare configuration narrows who could have written a manifest.
- **The fallback is uneven.** A checkout without a usable `.git` gets `unknown` for both, so two such manifests cannot be told apart at all.
- **The key is not rotated and not backed up.** Deleting it changes every later digest; nothing warns that earlier manifests no longer match.
- **No test scans the tracked tree.** The suite checks what is written, not what is committed; a manifest produced with `--record-host` and committed is not caught.


## Developer demo (2026-09-30)

`examples/cli_demo/` is the one canonical local journey: contract, gateway, an
allowed call, a denied call, and evidence that is read back and verified. It needs
no key, model or network beyond localhost, and `python examples/cli_demo/run_demo.py`
runs it unattended; `tests/integration/test_cli_demo.py` runs it in the suite. It
uses only public API. Building it found the items below.

### `causalmesh policy validate` crashed on the SDK sections (fixed)

**Status:** fixed 2026-09-30. Run with no path, `validate` located the file with
`Contract.find`, which parses it with the strict core schema. That schema rejects the
SDK-only `agent:` and `tools:` sections, so the repository's own
`examples/causalmesh.yaml` crashed the command with a traceback, and so did any
invalid contract. It now finds the file without parsing it and lets `load_sdk_config`
report. Pinned by `tests/integration/test_cli_policy_validate.py`; reverting the fix
makes four of its six tests fail. The command had no tests before.

### The CLI reads two contract schemas

**Status: fixed (commit `08088a7`).** `policy show`, `policy check` and `serve` used to load the strict core schema and refuse a contract with `agent:` or `tools:` (a clean error, exit 2) while `policy validate` and `CausalMesh.from_config` accepted both, so one file was valid to one command and rejected by another. The core schema now names and validates the two SDK sections (one implementation, `parse_sdk_sections`), and an unknown top-level key is still an error everywhere, so the typo guard that was the reason for leaving it is kept. Pinned by `tests/integration/test_contract_schema_unified.py` (a contract with SDK sections is accepted by the CLI and the library loaders, the gate builds the same contract with or without them, a misspelt top-level key is rejected, a bad SDK section is rejected by the core loader). The demo contract still leaves the two sections out, which is now a choice and not a workaround.

### `causalmesh verify` trusts the keys inside the artifact

**Status: narrowed, not closed (found and tested 2026-09-30; narrowed 2026-09-30; operator ring option closed 2026-10-12).** With no `keyring.json` beside `run.json`, `verify` still builds its key ring from the `actor_public_key` in the records it is checking (`cli/commands_verify.py`, `_key_ring_for`). That proves the chain is internally consistent and each signature matches the embedded key. It does not prove the key belongs to the named actor, which is what `verify_chain`'s own docstring and `docs/security.md` say a verifier must not rely on. Test: a chain produced by a second `CausalMesh` with an attacker's seed verifies as valid against the ring `verify` builds, and is rejected against the operator's ring.

What changed: `verify` now prefers a `keyring.json` beside `run.json` (which `CausalMesh.export` writes), reports which source it used (`keys`: `keyring.json` or `embedded`), and fails a run whose `keyring.json` is present but unreadable rather than falling back. A chain re-signed under a foreign seed fails against the keyring, and the same forged chain with the keyring deleted still passes (pinned as the known limit). **Closed 2026-10-12:** `verify --keyring PATH` (the same option as `--keys`; both spellings are accepted) takes an operator-supplied ring from anywhere: a directory of `<agent>.pub` / `<agent>.key`, or one `keyring.json`, in the format `crypto/keyring.py` documents and `CausalMesh.export` writes. A chain signed by a key the ring does not hold fails with an ASCII message naming the mismatch, for `--run`, `--id`/`--all`/`--latest` and `--evidence` alike. Without it the output still exits as before and now says, once, that the signatures were checked against keys embedded in the artifact and are not pinned. Pinned by `tests/adversarial/test_verify_keyring.py` (a chain tampered, re-chained and re-signed under a fresh attacker key passes without `--keyring`, as documented, and fails with the legitimate ring) beside `tests/integration/test_cli_verify_attribution.py`. **What is still not built:** automatic pinning of `key_ring_fingerprint` (a run does not record the fingerprint it expects, so nothing compares it), and any of this for experiment runs unless a ring is passed or a `keyring.json` is placed by hand. The ring is only as trustworthy as the channel it arrives by. The keyring is only as trustworthy as the channel it arrives by; see "SDK export and verification". Not exploited.

### An SDK session cannot be verified from the CLI

**Status: fixed for an exported session (2026-09-30).** `CausalMesh.export(directory)` writes `run.json` and `keyring.json`, and `causalmesh verify --run <directory>` verifies them, with no change to `verify`'s input format (see "SDK export and verification"). Verifying with a key ring the operator builds, as `examples/cli_demo/verify_evidence.py` does with `KeyPair.derive(seed, agent)` over `CausalMesh.agents`, is the stronger check, and since 2026-10-12 `causalmesh verify --keyring PATH` does the same from the command line (see "`causalmesh verify` trusts the keys inside the artifact"). **What remains:** a session that was never exported (a crash) leaves `chain.jsonl` and `keyring.json` but no `run.json`, which `verify --run` cannot read, and `serve` exports nothing.

### The README's `policy check --agent buyer` example answered ALLOW

**Status:** fixed 2026-09-30 in the README. The starter contract comments out the
`buyer` role, and an agent the contract does not name is unrestricted, so the example
only refuses once that role is uncommented. The README now says so.

## Found while folding the implementer notes (2026-09-30)

Each of these was reported by the implementer who hit it, or found by reading the code when two notes were put side by side. None is fixed here; each says why.

### Runner leases are taken under raw paths, so `ContractGate`'s claim rule never fires on them

**Status: open. Verified by an implementer, not fixed, because fixing it changes what contract-gated C3 runs measure.** `tasks/runner.py` acquires each agent's `task.role_for(agent).owns` entries as written (`src/a.py`), while `ContractGate` asks `may_write` with `Resource.path(...).identity` (`path:src/a.py`). A registry holding `src/a.py` answers `granted=True` to `may_write(path="path:src/a.py")` for a second agent and `False` for `may_write(path="src/a.py")`. So in a contract-gated experiment run (a `causalmesh.yaml` was found, which is the default) the `claim` rule never fires on those leases, while ownership and the other rules still do; the narrow `ClaimGate` the arms install without a contract keys on the raw path and does fire. The SDK does not have this problem, because `mesh.claim()` leases on the identity. Read against the code when this was folded: `runner.py` passes `path=path` to `claims.acquire`, and `Gate._rule_claim` passes `resource.identity`.

**Why it is recorded and not fixed:** the two arms' enforcement contrast (C2 against C3) is what the experiment measures, and a contract-gated C3 run currently enforces through ownership alone. Changing the key changes what those runs measure, so it is a decision for whoever owns the experiment arms: acquire on `identity`, or make the registry normalise kind-prefixed and bare paths to one key. Until then, do not read a contract-gated C3 run's denials as evidence about leases.

### The section 37 gate cannot tell a missing test runner from no effect

**Status: fixed (2026-10-03).** `python -m pytest` with no pytest installed exits 1, the same code as a failed test, so every arm failed identically and `check_sensitivity` reported NOT SENSITIVE for a reason unrelated to the task; it happened when `interface_consumer` and `shared_utility_refactor` were first gated, and the existing tasks shared the hazard. `integration_test_preflight` (`tasks/runner.py`) now asks the harness's own scrubbed environment, the one the test will really run under, whether the executable resolves and, for the `<python> -m <module>` form every shipped task uses, whether the module imports. `check_sensitivity` runs it first, runs no arm when it fails, and returns a `SensitivityReport` with `could_not_run` set (`sensitive` False, summary "COULD NOT RUN - <reason>"). `could_not_run` is added to `to_dict` only when set, so existing evidence keeps its shape; the CooperBench batch records such a pair as `failed` at stage `sensitivity` with `gate_could_not_run`, not `not_sensitive`. `tests/unit/test_gate_preflight.py` covers a missing module, a missing executable, the harness-versus-this-process environment distinction, and that no arm runs. **What remains:** only the `-m <module>` form is probed. A task whose command is any other shape is assumed runnable, and a runner that exists but is broken (a half-installed pytest, say) is not detected.

### `_execute_one` catches `BaseException`

**Status: fixed (2026-10-03).** `ExperimentRunner._execute_one` (`scheduler/loop.py`) caught `BaseException`, so a cancelled collection (Ctrl-C reaches it as `CancelledError`) recorded the in-flight run `FAILED` ("harness raised"), which is terminal and never retried, turning an operator's interrupt into a permanent failure in the denominator. `CancelledError`, `KeyboardInterrupt` and `SystemExit` now propagate with nothing recorded: the run stays `RUNNING`, the next startup marks it `ABANDONED`, and it resumes. The watchdog's own cancellation is unaffected (it yields `None`, not an exception, so the timeout path is unchanged). `tests/integration/test_scheduler_interrupt.py` cancels a real collection, checks the run is still `RUNNING` with no artifact, then resumes and completes it (`attempts == 2`); against the old handler it fails (`DID NOT RAISE`). Ordinary exceptions still become `FAILED` as before.

### The watchdog is cooperative only

Recorded in full under "Timeout as a distinct run state": cancellation lands where an agent `await`s, so a run wedged in a blocking call (including the synchronous integration check) blocks the event loop and the watchdog cannot fire, and a run that swallows cancellation is abandoned after `timeout_grace_s`, not killed. Listed here as well so a reader looking for limits of the run-timeout feature finds it.

### One intermittent failure seen once

**Status: not reproduced, not explained.** `tests/reproducibility/test_collection_determinism.py::test_two_collections_produce_identical_chains` failed once under `pytest -n 2` alongside other suites while the scaling work was being tested, and passed on every rerun, alone and in the same combination. Noted rather than explained. Relevant because it is a determinism test: if it recurs, treat it as a finding about the chain, not as flakiness.

### Ad-hoc scripts can import the wrong checkout

**Status: fixed for the test suite (2026-10-12); open for ad-hoc use.** With an editable install, `python -c "import causalmesh"` from a git worktree can resolve to a different checkout's `src` (this happened during the scaling work, and again on 2026-10-12: the editable install pointed at a stale `.worktrees/real-agent-hardening` checkout). `pytest` itself is unaffected because `pyproject.toml` sets `pythonpath = src`, but a subprocess does not inherit that, so `tests/integration/test_cli_demo.py::TestTheJourney` ran `examples/cli_demo/run_demo.py` against the stale tree and died with `create_app() got an unexpected keyword argument 'agent_tokens'`. **Fixed in the tests:** that test and `TestTheImportOrderThatOnlyAFreshInterpreterSees` (`tests/gateway/test_resource_kinds.py`) now pass `PYTHONPATH=<this repo>/src`, ahead of any existing value, to the subprocess; the other subprocess tests that import `causalmesh` already did (`test_cli.py`, `test_evidence_crash.py`, `test_import_boundaries.py`, `test_cleanroom_verification.py`, `test_claim_exclusivity.py`, `tests/support/serve_process.py`). **What remains:** a person running `examples/cli_demo/run_demo.py` or any ad-hoc script directly still gets whichever checkout the editable install points at and needs `PYTHONPATH=src` (or `pip install -e .` from the intended tree); the demo does not guard against it. `causalmesh doctor` does not report which checkout is imported.

### The main-into-dev merge left the head broken, and nothing ran the gate on it (2026-10-03)

**Status: repaired; the process gap is open.** `d710942` ("Merge branch 'main' ... into dev") kept one side's constructor and the other side's methods in `sdk/mesh.py`, `cli/commands_verify.py` and `gateway/gateway.py` (two parallel implementations of SDK persistence and of `verify` key handling had landed independently). The merged tree failed 329 tests and errored 141 more, and `ruff` reported undefined names (`records`, `threading`, `EvidenceStore`, `verify_chain`); the full suite had not been run on it. Repaired in `c82c202` by reconciling both designs rather than choosing one: `persist_to` and `evidence_path` both stay and are mutually exclusive per session (passing both is a `ConfigurationError`, since two writers to two files would be two chains); `verify` prefers the operator's `--keys` ring, then a `keyring.json` beside `run.json` (a broken one fails the run), then the embedded keys, and only `--keys` counts as attribution checked. The full gate then passed (2804 passed, none skipped for a missing extra). **What remains:** there is no CI (see "CI was removed"), so a merge is only as safe as someone remembering to run `python scripts/check.py` on the result. Two persistence mechanisms for one chain is also real surface area to carry; unifying them (one store, two views) is the cleaner end state and was not attempted inside a repair.

### Two bugs found in tests while getting the gate green (2026-10-03)

**Status: fixed.** `test_cli_verify_attribution`'s ASCII check excluded only light box-drawing characters, so it failed wherever Rich draws a heavy box (it now excludes the whole Box Drawing block). `policy/ledger.py` built a `SELECT` with an f-string (flagged by bandit at medium; ruff's `noqa` does not silence bandit), now a lookup of two whole literal queries. `docs/preregistration-draft.md` said two tasks were plannable and 960 runs; there are four and `experiment plan --profile confirmatory --allow-gated` plans exactly 1920 (checked), so the draft's "discrepancy" is resolved and says so.


### Thirteen tests "failed only in the full run": it was the invoking shell, not test order (2026-10-12)

**Status: fixed in the tests and in the runner's `bash` resolution; the guard against a real leak was not added because there was none.** A full `python -m pytest -q` failed 13 tests (`test_adoption_hook::TestClaudeCodeHookAdapter` x3, `test_cli::TestModuleEntryPoint`, `test_cooperbench_batch_run::TestThreeWayMerge` x2, `test_cooperbench_hidden_tests` x3, `test_welcome::TestPalette` x3 and `TestOnboardUsesTheSharedPalette` x1) that passed "alone". They were assumed to be a state leak from an earlier test. **How it was found:** a pytest plugin that snapshots `os.environ`, the working directory, `sys.path`, `sys.modules` entries set to `None`, the locale and `sys.stdout` around every test reported no mutation across `tests/adversarial`, `tests/gateway` and `tests/integration` up to `test_cooperbench_hidden_tests.py` (678 passed) or across `tests/unit` (the one `sys.path` entry it flagged was a reorder, not a change of content). The same 13 then failed **standalone** under the PowerShell tool's environment and passed standalone under Git Bash, so the variable was the shell the run was started from. In that environment `NO_COLOR=1` and `PYTHONIOENCODING=utf-8:surrogateescape` are set, and `PATH` has `Git\cmd` but not `Gitin`, so a bare `bash` is the WSL relay at System32 (exits 1 with no distro, the same code as a failed test).

**Causes and fixes.** (1) `NO_COLOR`: rich honours it even with `force_terminal=True`, so `TestPalette.codes` saw no escape codes; it now pins `no_color=False`. (2) `PYTHONIOENCODING=utf-8` made the child of `test_python_dash_m_causalmesh_runs_the_cli` draw UTF-8 box glyphs that the parent decoded as cp1252 (byte 0x90 is undefined there); the test now sets the child's encoding and decodes as UTF-8. (3) `bash`: the runner and two tests resolved it with `shutil.which`, which returns the relay when `Gitin` is not on PATH. `tasks.runner.resolve_executable` now probes `bash -c "exit 0"` on Windows, falls back to the Git for Windows `bash` beside `git`, and returns `None` otherwise, so `integration_test_preflight` reports "cannot run" instead of every arm failing. Pinned by `tests/unit/test_resolve_executable.py`. **Verified:** the 13 pass standalone and inside the 31-file prefix that precedes them, from both PowerShell (`NO_COLOR=1`) and Git Bash. **What remains:** `tests/unit/test_x402_pay.py::TestBudgetInterplay::test_concurrent_payments_cannot_overspend_together` paid 3 of the expected 4 once under load and passed 6 of 6 alone; it is not explained (see "One intermittent failure seen once" for the standing policy). `scripts/check.py` does not pin `NO_COLOR` or `PYTHONIOENCODING`, so a test that reads either from the ambient environment can still be written; the fix here is per test.

## Claim enforcement: what the audit of 2026-10-12 found missing

Found by the read-only audit in `docs/SHIP-AUDIT.md` (section 3) and re-read against the code on 2026-10-12; each entry names the lines it was read at. Entries (a) to (i) are properties a reader of the README would reasonably assume exist; (j) was found while re-reading the hook. None is fixed here. Every run and test behind the claims below used a deterministic mock agent or synthesized input, on one Windows 11 machine. The status of each claim these gaps limit is in `docs/claims-ledger.md`. Severity is the owner's to re-rank: **high** means the headline claim is false without it, **medium** means a real failure is reachable but narrower.

### (a) The Claude Code hook never consults claims

**Status: open. Severity: high.** `causalmesh policy check --stdin` builds `Gate(contract, run_id="policy-check", enforcing=contract.arm == "C3")` with no `registry` (`src/causalmesh/cli/commands_policy.py:179`) and asks it at `now_us=0` (`:180`). `Gate._rule_claim` returns `None` when `self.registry is None` (`src/causalmesh/policy/gate.py:381-382`), so the claim rule is inert on this path. The example hook (`docs/examples/claude-pretooluse.sh:57-30`) only calls that command. **User impact:** with `docs/adoption.md` wired as written, two Claude Code sessions editing one file are refused only if the contract assigns the path to a different role; another session's live lease changes nothing. "Prevents conflicting writes between Claude Code agents" is therefore not true through the hook (the library and gate do refuse, see `tests/unit/test_policy.py::TestClaims`). **Acceptance test:** in a subprocess test, agent A takes a lease on a path in a `ClaimRegistry` database that the hook is pointed at; the hook, run as agent B (needs (j)), returns `deny` with a `permissionDecisionReason` that names A and the path; the same call run as A returns `allow`; with the database deleted B is allowed (the control). The lease must be taken under the key the gate asks for, `Resource.path(...).identity`, which is the open problem in "Runner leases are taken under raw paths, so `ContractGate`'s claim rule never fires on them" above, and the gate must be given a clock that agrees with the lease's (the CLI passes `now_us=0`). A mutation check: building the `Gate` without the registry makes that test fail.

### (b) The hook covers `Write` and `Edit` only

**Status: open. Severity: high.** The adapter maps only `Write|Edit` to a path check and returns `allow` for every other tool name (`docs/examples/claude-pretooluse.sh:44-47`), and `docs/adoption.md` wires the matcher as `"Write|Edit"` (section 2). `MultiEdit`, `NotebookEdit` and `Bash` are never gated. **User impact:** an agent that writes through `Bash` (a redirect, `sed -i`, a script) or through `MultiEdit` is not checked against ownership at all, so the contract is a convention for the tools it names and no bound on the agent. Whether `NotebookEdit` carries its path in `file_path` or in another field of `tool_input` is UNKNOWN (not verified against Claude Code). **Acceptance test:** a payload with `tool_name` `MultiEdit`, and one with `NotebookEdit` (with the field names Claude Code actually sends, cited), on another role's path returns `deny`. For `Bash` the acceptance is a recorded decision, pinned by a test: either a rule that gates it (and what that rule can and cannot see in a shell command) or an explicit statement in `docs/adoption.md` that `Bash` is outside the hook.

### (c) No fencing tokens

**Status: open. Severity: high, together with (d).** A search of `src/` and `docs/` for "fencing" finds nothing outside `docs/SHIP-AUDIT.md` and this entry. Expiry is lazy: `_live_holder` ignores a lapsed lease by comparing `expires_at_us > now` at read time (`src/causalmesh/claims/registry.py:303`), and nothing on the write path carries a token. **User impact:** a holder that is paused or slow past its lease is not stopped when it resumes; if another agent has taken the path in the meantime, both writes land and the second silently overwrites the first. **Acceptance test:** a property test where holder A's lease lapses, B acquires, and A's write presented with its old token is rejected by the write path while B's is accepted; plus a mutation check that removing the token comparison makes the test fail. Tokens must be monotonic per resource.

### (d) No automatic lease renewal or heartbeat

**Status: open. Severity: medium.** `docs/claims.md` shows `renewal_interval_seconds: 30` as a default; a search of `src/` finds no reader of that key and no caller of `ClaimRegistry.renew` (defined at `src/causalmesh/claims/registry.py:420`). The registry extends a lease only on an explicit `renew` or on a re-`acquire` by the holder (`:341`, `:381`). **User impact:** a holder working longer than `duration_seconds` loses the path with no warning and, without (c), keeps writing. The configuration block in the docs reads like behaviour and is not. **Acceptance test:** a holder doing work for three lease durations keeps the path (a second agent is denied throughout) with renewal on; when the holder stops, the path is free within one duration plus one interval; and the interval is read from the contract, or the block is removed from `docs/claims.md`.

### (e) No atomic multi-resource acquire

**Status: open. Severity: medium.** `acquire` takes one path under one `BEGIN IMMEDIATE` transaction (`src/causalmesh/claims/registry.py:325-418`); callers that need several take them in a loop (`src/causalmesh/tasks/runner.py:351-360`). Handoff is `release` (`:471`) then `acquire` (`:325`), two transactions. **User impact:** two agents that each need paths X and Y and take them in opposite order can each end up holding one, and a handoff leaves a window in which a third agent can take the path. **Acceptance test:** across processes (the pattern of `tests/property/test_claim_exclusivity.py::TestCrossProcessContention`), two contenders each request {X, Y} in opposite order; exactly one is granted both and the other holds neither, and no denial names a path the loser also holds.

### (f) The runner discards `ClaimOutcome`

**Status: open. Severity: medium.** `tasks/runner.py:351-360` calls `claims.acquire(...)` for each owned path and does not read the returned `ClaimOutcome`; a search of `runner.py` for `.granted` finds nothing. **User impact:** an agent whose lease was refused (two roles owning one path) proceeds as though it held it; the registry records the denial but the run does not act on it, so a C3 result can describe an agent that was never actually protected. This is separate from the raw-path key problem in "Runner leases are taken under raw paths, so `ContractGate`'s claim rule never fires on them" above, and fixing it changes what C3 runs measure for the same reason, so it is the experiment owner's decision. **Acceptance test:** a task in which two roles own one path: the refused acquire leads to no write by the refused agent and a recorded denial, and the run artifact says so.

### (g) No test drives a real `claude` session

**Status: open. Severity: high for the adoption claim.** `tests/integration/test_adoption_hook.py` runs the script in a real `bash` subprocess with a hand-written JSON payload (`run_hook`); no test, and no recorded run, has `claude` call the hook. The payload shape is the one `docs/adoption.md` describes, which is this repository's reading of Claude Code. **User impact:** whether a real session sends that shape, finds the script and the contract from its working directory (the settings example uses the relative command `docs/examples/claude-pretooluse.sh`, and `Contract.find` starts at the hook's cwd), and honours `permissionDecision: deny`, is UNKNOWN. **Acceptance test:** one recorded run with two real `claude` sessions on one file, with the `claude` version, the settings used and the hook's own log kept under `docs/evidence/`; the run shows a denial and shows what the refused session did next. An automated version is marked `slow` and skips when `claude` is absent.

### (h) The hook's behaviour when its inputs are bad is unpinned

**Status: script fixed 2026-10-13; the real-session half stays open under (g).** `docs/examples/claude-pretooluse.sh` no longer exits with a bare code: every failure below, a non-object payload and a `Write`/`Edit` with no `file_path` print a `deny` JSON with a non-empty reason and exit 0, and `TestHookFailsClosed` in `tests/integration/test_adoption_hook.py` pins each case (11 tests, all failing against the previous script). `jq` is stated as a prerequisite in `docs/adoption.md`. What is still UNKNOWN is whether a real Claude Code session honours that `deny`; that is entry (g). The original observation follows.

**Original status: open. Severity: high.** Observed 2026-10-12, Git Bash on Windows 11, the script run as `echo <json> | bash docs/examples/claude-pretooluse.sh` from a directory holding a valid `causalmesh.yaml`: (1) stdin that is not JSON: exit 5, a `jq` parse error on stderr, nothing on stdout; (2) `jq` not on `PATH`: exit 127, nothing on stdout, even for a tool name that would be allowed; (3) `causalmesh` not on `PATH`, or no `causalmesh.yaml` in the working directory: exit 0 and a `deny` whose `permissionDecisionReason` is the empty string. The script sets `set -euo pipefail` (`docs/examples/claude-pretooluse.sh:6`) and swallows the CLI's failure with `|| true` (`:30`). No test covers any of these. **What is UNKNOWN:** whether Claude Code treats a hook that exits 5 or 127 with no output as a block or as a non-blocking error that lets the tool run; nobody has checked this against a real session, and Claude Code's documentation of hook exit codes was not read for this entry. If it is non-blocking, cases (1) and (2) fail open. **User impact:** a machine without `jq` (it is not installed by `pip install causalmesh`) may run the hook as an allow-everything no-op with no visible sign. **Acceptance test:** subprocess tests for the three cases above, each asserting the documented outcome; the script changed so (1) and (2) produce a `deny` JSON (or the exit code Claude Code documents as blocking, cited) and (3) carries a non-empty reason; and `docs/adoption.md` states `jq` as a prerequisite.

### (i) No cross-machine coordinator

**Status: open, and a stated non-goal of the slice. Severity: high for anyone who expects it.** `docs/claims.md` ("What this does not do") says SQLite serializes within one filesystem. `causalmesh serve` builds no `ClaimRegistry`: a search of `src/causalmesh/server/` and `src/causalmesh/cli/commands_serve.py` for `claim` and `ClaimRegistry` finds no use of the registry; it is a gate-and-record proxy for model and tool calls. `ClaimRegistry` takes a database file path (`src/causalmesh/claims/registry.py:179`). Whether the registry is correct on a network filesystem is UNKNOWN (not tested). **User impact:** agents on two machines, or in two containers without a shared volume, do not see each other's leases; exclusivity does not hold between them. **Acceptance test:** (from `docs/SHIP-AUDIT.md`, C2) a two-machine test in which a partitioned stale holder's write is rejected by token; it depends on (c).

### (j) The hook gives every session the same identity

**Status: open. Severity: high for (a) and for ownership between sessions.** The adapter hard-codes `agent_id` as `claude-code` (`docs/examples/claude-pretooluse.sh:57`). **User impact:** every Claude Code session is one agent to the gate, so a contract that gives two roles different paths cannot tell two sessions apart, and once (a) is fixed a second session would be treated as the holder of the first session's lease and allowed. Whether Claude Code's hook payload carries a stable per-session identifier that could be used is UNKNOWN (not verified). **Acceptance test:** the adapter takes the agent id from a source the operator controls, not from the tool input the agent writes; a test runs it with two ids against a contract with two roles and gets different verdicts for the same path.
