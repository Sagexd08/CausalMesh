# The task system

Spec §35 to §38. A task bundles everything a run needs to be reproducible:
a repository fixture, agent roles, a declarative scenario, success criteria
and a version.

Tasks are **data, not code**. A task that could execute arbitrary Python
would make "the same task" unverifiable across machines, and the
configuration hash (§33) would no longer pin what actually ran.

Status: describes Step 9 of `docs/PLAN.md`. Four authored tasks exist, one per
§35 family: `schema_handler_widen` and `interface_consumer` and
`shared_utility_refactor` (dependency shapes) and `concurrent_edit_collision`
(contention), plus the synthetic CooperBench import and a generated N-agent task
(below). What each shows, and what is not claimed, is in `docs/backlog.md`.

## What makes a task coordination-sensitive

§37 is emphatic:

> A task must demonstrate empirically that the coordination dependency
> actually exists. Do not assume a task is coordination-sensitive merely
> because its YAML says it is.

There are **two shapes**, and the validator was initially wrong about this:

| Shape | Mechanism |
|---|---|
| **Contention** | Two agents write the same path |
| **Dependency** | Agent A writes a path agent B declares a dependency on |

The first version of the validator required contention and rejected
`schema_handler_widen`, which has none. Running the task settled it: with
no contested path at all, C0 fails and C1/C2/C3 succeed. The rule was
wrong, not the task. The dependency shape is the whole schema/handler
family (§35), so demanding contention would have excluded a quarter of the
planned benchmark.

The same correction applies to the divergence check: a divergence file must
be **written by someone**, but need not be contested. Stale-dependency
defects show up in a file only one agent writes, invalidated by a peer's
write elsewhere.

## Success (§38)

```
success = integration tests pass  AND  induced divergence absent
```

Both, never either. A run whose tests pass while the divergence marker
remains has not resolved the coordination problem — it failed to notice it,
which is exactly the C0 failure mode an "either" rule would hide.

There is no subjective field anywhere in the outcome module. The primary
outcome of the whole experiment is this boolean, and a human judgement in
the middle of it would make the result unreproducible.

A **missing** divergence file is not "no divergence": the check could not be
performed, and reporting success on that basis would be a false negative.
Likewise, tests that never ran are recorded distinctly from tests that ran
and failed.

## Success is judged on an integrated workspace

Agents have separate workspaces (§11), but that is an *isolation
mechanism*, not the research model. The experiment is about agents
coordinating over a shared codebase that is later integrated.

Judging a single agent's copy asks the wrong question — whether that
agent's local view is self-consistent — when what matters is whether the
combined work is. So each run merges the workspaces, taking every file from
the agent whose role owns it, which is what an ownership-based merge does
and the same rule the claim registry enforces under C3.

This was discovered by running the task: judging agent_b's copy made C3
fail, because enforcement correctly refused agent_b's write to a file
agent_a owned, leaving agent_b's local view inconsistent. The claim
semantics were right; the judging was wrong.

## Contested paths: last writer, or a three-way merge

A path both agents may edit is `contested`. `contested_merge` in the task file says how
the integrated workspace resolves it.

- `last_writer` (the default, and the only behaviour before this field existed): the
  whole file comes from the agent that wrote it last, per the signed chain. One of two
  agents editing one file is always lost, whatever either was told. A task that never
  mentions the field hashes and scores exactly as before.
- `three_way`: the two agents' files are merged against the fixture they started from
  (`causalmesh.tasks.merge3`, pure Python, no dependency). Edits to different parts of a
  file both survive. Edits to the same lines, or to adjacent lines, are a conflict, the
  rule git uses. A conflict is recorded on the result (`merge_conflicts`), the conflicted
  file carries git-style markers, and **the run does not succeed however its tests
  score**: CooperBench's own criterion is that the changes merge cleanly *and* pass.

`RunResult.merge_conflicts` is `None` for `last_writer` (nothing was merged, so nothing
is known) and a possibly empty list for `three_way`. Those are different statements.
Changing a task's strategy changes what success means for it, so it changes the task's
`content_hash` and should come with a `version` bump.

The merge is line based. It cannot see that two edits to different lines are
semantically incompatible, and on the real CooperBench pairs that does happen: click
`task2800` merges cleanly and then fails feature 2's tests, because one feature closes
a context on exit and the other fires a callback on close. That is the kind of failure a
coordination benchmark exists to expose, and it is what the integration test is for.

## Running the real CooperBench dataset

```bash
git clone --depth 1 https://github.com/cooperbench/CooperBench
python scripts/import_cooperbench.py --dataset-root CooperBench --cache-dir <dir> \
    --output-dir <dir> --contested-merge three_way --jobs 4
```

Imports every feature pair (652), stages each as its own task, fetches only the base
files its patches touch, and runs the section 37 gate with an **offline** success oracle
(the merged files must hold both features' line changes; no code from the target
repository is executed). It needs the network once for the base files and takes about
a minute and a half with four jobs. `scripts/cooperbench_real.py` is the stricter, slower
path: a full checkout and the generated pytest harness, for the few pairs whose
repository can run here (`gate`), plus `merge-check`, which validates the merge against
`git merge-file` and CooperBench's own gold conflict report on all 652 pairs.

Every run is a scripted mock agent replaying gold patches. The arms cannot differ, so the
gate says NOT SENSITIVE for every pair whatever the merge; read
`summary.gated_with_isolated_success` (how many pairs the platform solves) and not the
verdict. Results: `docs/backlog.md`, "CooperBench import".

## The two dependency tasks added later

`interface_consumer` (`quote(item)` becomes `quote(item, region)` with no
default; the consumer's stale call fails with `TypeError`) and
`shared_utility_refactor` (`slugify` becomes `make_slug(text, *, sep)`, old name
removed; the stale call fails with `AttributeError`, and the utility has two
callers owned by different agents). Both are dependency-shaped: ownership is
disjoint and nothing is contested, so C3 equals C2 on both. Their real §37 gate
verdicts with the mock agents are SENSITIVE (C0 0/2, C2 2/2). The dependency
exists by construction in three layers of unequal strength, and the stale-versus-
informed branch in the script is **authored, not discovered**: the verdicts
confirm the construction is wired correctly, they are not an estimate of how often
real agents would break such an interface. See `docs/backlog.md` ("Remaining task
families").

**A hazard the gate used to share, now closed:** the integration test runs
`python -m pytest` with the `python` on `PATH`, and if that interpreter has no pytest
the test fails in every arm, which used to read as "the arms do not differ".
`check_sensitivity` now runs `integration_test_preflight` first, against the harness's
own scrubbed environment. If the executable or the `-m` module is not there it runs
no arm and reports `COULD NOT RUN` with the reason (`SensitivityReport.could_not_run`),
not a verdict. Only the `<python> -m <module>` form is probed; any other command shape
is assumed runnable, so a task that uses one still needs its runner checked by hand.

## Generated tasks for N agents

`causalmesh.tasks.scaled` generates a task for N agents from `ScaledSpec`
(agents, contention group size, files per agent). The task and its fixture are
produced in memory and in a scratch directory; nothing is added to `tasks/` or
`fixtures/`, so it is not part of any run plan. It exists for
`causalmesh experiment scalability`.

## Measured results

`schema_handler_widen`, all four arms, real fixture and real agents:

| Arm | Success | Tests | Divergence absent | Coordination bytes |
|---|---|---|---|---|
| C0 | ✗ | ✗ | ✗ | 0 |
| C1 | ✓ | ✓ | ✓ | > 0 |
| C2 | ✓ | ✓ | ✓ | > 0 |
| C3 | ✓ | ✓ | ✓ | = C2 |

C2 and C3 spend **identical** coordination bytes, as they must: they differ
by enforcement alone, and any difference in information cost would confound
the contrast.

The §37 gate reports `SENSITIVE — C0 0/2, C2 2/2`, with divergences 2/2 in
C0 and 0/2 in C2.

## How the mock agent responds to information

A scripted agent that always does the same thing cannot show an information
effect: it would act identically in every arm. §9 requires the mock to be
capable of "responding to coordination events", and the plumbing existed
(observe → channel → injection) without ever affecting behaviour.

Actions therefore take optional guards:

```yaml
- write:
    if_informed_about: src/schema.py    # only if told about that path
    path: src/handler.py
- write:
    if_uninformed_about: src/schema.py  # only if not told
    path: src/handler.py
```

The agent stays deterministic — the same observations always produce the
same behaviour — while its behaviour now depends on what it was told, which
is exactly the factor the experiment manipulates.

**Only injected events count as informed.** An event the relay delivered
but the window dropped (§18) never reached the agent's context, and
treating it as known would credit an arm with information it did not
receive. A skipped action is recorded with its reason, so an agent's
inaction is evidence rather than a silent absence (§52).

## Two bugs the first real execution exposed

**The scrubbed environment omitted `APPDATA`.** On Windows, user-site
packages live under `%APPDATA%\Python`, so `python -m pytest` failed with
"No module named pytest" and **every task's integration test failed
identically in every arm**. The experiment would have reported uniform
failure while appearing to run.

**A digest of non-reproducible bytes is still non-reproducible.** After
excluding command output from the signed payload, I added an
`output_sha256` of that output — which reintroduced the exact failure it
was meant to fix, hidden behind a hash rather than visible as text. It is
now excluded entirely; full output lives in the run artifact, where a human
can read it and no chain depends on it.

## Validation

Structural validation (§36) runs on every task and is cheap. The quality
gate (§37) runs the task under C0 and C2 and is expensive, deliberately.

C2 rather than C3 is the comparison arm: C3 adds enforcement on top of
information, so a C0-versus-C3 difference could come from either factor,
while C0 versus C2 isolates information alone.

Errors block a task from running; warnings do not. Collapsing the two would
either block valid tasks or admit broken ones.
