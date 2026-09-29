# SYNTHETIC CooperBench-shaped sample — test fixture, not real data

Everything under this directory is hand-written for
`tests/unit/test_cooperbench.py` and
`tests/integration/test_cooperbench_import.py`. It is **not** a copy of, or
derived from, the real CooperBench dataset
(github.com/cooperbench/CooperBench). This sandbox has no network access to
fetch that dataset, so a small stand-in was built by hand instead, mimicking
the documented raw layout closely enough to exercise the loader:

```
dataset/
  tinyrepo/
    task1/
      setup.sh
      run_tests.sh
      feature1/
        feature.md
        feature.patch    # real `git diff` output against base_repo/
        tests.patch       # placeholder — see the file's own comment
      feature2/
        feature.md
        feature.patch    # real `git diff` output against base_repo/
        tests.patch
base_repo/
  src/greeter.py
  src/utils.py
  tests/test_greeter.py
```

`base_repo/` is the pre-patch state `causalmesh.tasks.cooperbench.import_task`
needs as `base_files` — it is not part of the CooperBench schema itself,
just this test's way of supplying the "checked-out repository" the real
loader would read from a real clone.

Both `feature.patch` files are real unified diffs (produced with
`git diff`, not typed by hand) against `base_repo`, and both touch
`src/greeter.py` — deliberately, so the loader's contested-path discovery
(`touched_paths` intersecting the two features' path sets) has something
real to find: `feature1` adds a `"formal"` greeting style, `feature2` adds a
`"friendly"` one, and `feature2` additionally touches `src/utils.py` alone
(a disjoint, feature2-only path, to prove `owns` is computed correctly too).

Nothing here should be cited as evidence about real CooperBench tasks —
see `docs/backlog.md`, "CooperBench import (§54)".
