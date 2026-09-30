### CooperBench import (§54): run against the real dataset

Fragment for `docs/backlog.md`, to replace the status line and the "does not
claim" / "what it would still take" paragraphs of the existing §54 entry.

**Status: the loader has now been run over the real CooperBench dataset. All
30 tasks, 199 features and 652 feature pairs import with 0 failures. The real
§37 gate was run on 3 pairs and returned NOT SENSITIVE for all 3. Nothing
about any agent's behaviour is claimed; every run used deterministic mock
agents replaying the dataset's own gold patches.**

**What was actually run.**

- `git clone --depth 1 https://github.com/cooperbench/CooperBench` succeeded
  from this environment (commit `63b9d44d9f39a02fccf5bf0052db48a917a011fd`,
  14 MB). The earlier "no network" limitation did not apply here.
- The loader's assumed layout was checked against the real `dataset/` tree.
  The directory shape `dataset/<repo>_task/task<id>/feature<N>/{feature.md,
  feature.patch,tests.patch}` is right, and all 199 feature directories have
  all three files. Four things the synthetic sample hid were wrong or
  missing, and each is fixed with tests:
  1. **A task is not two features.** 29 of the 30 tasks have 3 to 12
     features (one has 2); the unit of work is a pair, 652 in all. The old
     loader read `feature1` and `feature2` and ignored the rest, so it could
     reach 30 of the 652 pairs (4.6%) and would have said nothing about the
     other 622. `import_task(features=(i, j))`, `feature_numbers`,
     `feature_pairs`, and `import_dataset(pairs="all")` now cover every pair.
  2. **The base repository is not in the dataset.** Each task's `setup.sh`
     and `Dockerfile` name an upstream clone URL and a pinned `BASE_COMMIT`;
     nothing is vendored and nothing is a checkout. The published
     `akhatua/cooperbench-<repo>:task<id>` Docker images bake the same clone.
     `cooperbench_base.parse_base_spec` reads those two facts (text only,
     `setup.sh` is never executed; one task builds its URL from variables,
     which it resolves and refuses if any stays unresolved).
     `base_files_for_paths` fetches only the files a pair's patches touch with
     a blobless shallow fetch of the one commit, 44 MB for the 30 tasks in
     total, and `checkout_base_repo` writes a full tree when a run needs one.
     Network is needed the first time; a cache directory makes re-reads
     offline (tested).
  3. **Latent bugs, not hit by this data but real:** `touched_paths` read a
     removed line such as `-- a comment` (rendered `--- a comment`) as a file
     header; it now consumes hunks by their declared line counts (with a
     `---`/`+++`/`@@` look-ahead so a miscounted patch cannot swallow the next
     file). Text was read and written with universal-newline translation,
     which rewrites CRLF files; it now moves bytes. `git apply`'s throwaway
     repo no longer commits (one fewer hidden dependency on `user.name`).
     Checked against the truth: `touched_paths` agrees with
     `git apply --numstat` on all 199 `feature.patch` files.
  4. **The dataset's own `run_tests.sh` cannot be the integration test.** It
     is container-era: it installs dependencies from the network and takes
     patch paths as arguments. See the gate run below for what stood in.
- `import_dataset_report` (new) imports every pair and records each failure
  with a stage (`base_repo`, `import`, `definition`, `unexpected`) and a
  reason, instead of raising on the first one or dropping it.
  `scripts/cooperbench_real.py import` runs it and writes the summary.

**Real numbers: import** (`docs/evidence/cooperbench-real-import.json`, counts
and statuses only, no repository contents):

| | |
|---|---|
| tasks attempted / with at least one imported pair | 30 / 30 |
| features | 199 |
| pairs attempted / imported / failed | 652 / 652 / 0 |
| failures by reason | none |
| pairs with at least one contested path (same file edited by both features) | 652 of 652 |
| contested paths per pair | 1 path: 512 pairs, 2: 128, 3: 12 |
| pairs whose gold patches conflict under `git merge` (CooperBench's own `gold_conflict_report.json`) | 499 |
| pairs whose gold patches `git merge` cleanly | 153 |
| pairs that `validate_structure` (§36) passes, fixture check skipped | 652 of 652 |

Every pair's `feature.patch` applied cleanly to the real base files, so there
is no import failure to explain. Zero is a real result, not a filter: nothing
was skipped, and the report lists every pair. The 153 clean-merge pairs are
worth reading next to the gate result below: this platform calls them
contested too, because it contests by file, not by hunk.

**Real numbers: the §37 gate** (`docs/evidence/cooperbench-real-gate.json`,
produced by `scripts/cooperbench_real.py gate`). Pair `(feature1, feature2)`
of three tasks, fixed before any verdict was seen, chosen because they are
pure-Python repositories whose tests run with almost no dependencies: click
`task2800`, jinja `task1621`, dirty-equals `task43`. Each fixture is the whole
upstream tree at the pinned commit (not committed, not vendored).

The hidden-test harness is this loader's own (`hidden_tests="pytest"`), so it
was validated before its verdicts were used, against CooperBench's own two
stated properties: for all three tasks, every feature's tests FAIL on the
untouched base and PASS with `combined.patch` applied. The fidelity of the
materialized write actions was also checked byte for byte against
`git apply` of the same patch on the full checkout (9 actions, 0
differences; a one-off check, not committed).

| task | contested path | gate verdict, exactly as produced |
|---|---|---|
| click `task2800` f1,f2 | `src/click/core.py` | NOT SENSITIVE, C0 0/1, C2 0/1 |
| jinja `task1621` f1,f2 | `src/jinja2/loaders.py` | NOT SENSITIVE, C0 0/1, C2 0/1 |
| dirty-equals `task43` f1,f2 | `dirty_equals/__init__.py`, `dirty_equals/_other.py` | NOT SENSITIVE, C0 0/1, C2 0/1 |

Diagnostic (not the verdict): in each arm's integrated workspace, one
feature's tests pass and the other's fail, identically under C0 and C2 (click:
feature1 passes, feature2 fails; jinja and dirty-equals: feature1 fails,
feature2 passes). That is the same mechanism as the synthetic sample:
`tasks/runner.py::_integrate_workspaces` resolves a contested path to a
single last writer's whole file, so two features that both edit one file
cannot both survive, whatever either agent was told. No verdict was tuned.

**What this does not claim.**

- Nothing about agent behaviour. The mock agents replay gold patches.
- Nothing about the 649 pairs the gate was not run on. "Not sensitive" for 3
  pairs is not a claim about CooperBench. The mechanism above suggests any
  pair where both features edit one file is affected the same way, but that
  was not run.
- Not CooperBench's evaluation. CooperBench tests each agent's real patch, or
  the `git merge` of two, against per-feature tests; this platform integrates
  by file ownership and last writer. The generated harness also runs the
  Python test files each `tests.patch` touches, not the file list in the
  task's own `run_tests.sh`, so a pass here is not CooperBench's pass.
- Not a statement that the platform is wrong to be winner-take-all; only that
  it cannot express a same-file, different-hunk feature pair, which is the
  commonest shape here (512 of 652 pairs share exactly one file).
- The hidden tests are not hidden: `hidden_tests="pytest"` writes the
  `tests.patch` files into the fixture at `.cooperbench/`, so any future
  non-mock agent would see them. Fine for mock agents, not for real ones.

**What it would still take.**

- The gate on the other Python pairs. It costs a full checkout and a working
  test environment per task; `dspy`, `llama_index` and `datasets` need heavy
  dependencies that were not installed here. 24 of 30 tasks are Python; Go
  (3), JavaScript (2) and Rust (1) have no harness (import works for them,
  the gate does not).
- A content-level merge for contested paths (a real 3-way merge of the two
  features' patches), otherwise 499 of 652 pairs cannot succeed and the other
  153 cannot be told apart from them. That is a platform decision (it changes
  what "success" means for every task), not a loader change.
- Move hidden tests out of the workspace before any real agent runs.
- Pair selection for a real experiment (`subsets/lite.json` has 100 pairs);
  none was made here.

**Reproduce.**

    git clone --depth 1 https://github.com/cooperbench/CooperBench
    python scripts/cooperbench_real.py import --dataset CooperBench/dataset --cache <scratch>
    python scripts/cooperbench_real.py gate --dataset CooperBench/dataset --cache <scratch> \
        --work <scratch2> --task pallets_click_task/task2800 \
        --task pallets_jinja_task/task1621 --task samuelcolvin_dirty_equals_task/task43

The gate needs `pytest` plus `markupsafe` and `pytz` importable by `python`.
The summary files hold no timestamps, hostnames or absolute paths.

**Tests added:** `tests/unit/test_cooperbench_real_layout.py` (45),
`tests/integration/test_cooperbench_hidden_tests.py` (3). The old 30
CooperBench tests still pass unchanged. `pytest -m unit` has one failure,
`test_path_budget.py::test_a_run_that_cannot_fit_is_refused_before_anything_is_created`
(`File name too long` on Linux), which this change does not touch.
