# Fragment: TASKS track

Branch `feat/tasks`. Nothing here has been merged into `CHANGELOG.md`,
`README.md`, `docs/backlog.md` or `docs/tasks.md`; the sections below are
ready to paste.

## Summary

The two task families `docs/backlog.md` recorded as unbuilt now exist:
`interface_consumer` and `shared_utility_refactor`. Both are *dependency*
tasks (no contested path; one agent's write invalidates another's work),
both validate structurally with no errors and no warnings, and both were put
through the real section 37 gate (`check_sensitivity`, executed, not
asserted).

| Task | Agents | Stale-consumer failure | C0 | C1 | C2 | C3 | Gate (C0 vs C2) |
|---|---|---|---|---|---|---|---|
| `interface_consumer` | 2 | `TypeError` (called an old signature) | fail | pass | pass | pass | SENSITIVE, C0 0/3, C2 3/3 |
| `shared_utility_refactor` | 3 | `ImportError` (imports a removed name) | fail | pass | pass | pass | SENSITIVE, C0 0/3, C2 3/3 |

Divergences: C0 3/3 and C2 0/3 on both tasks. The one-repetition figures the
tests assert are C0 0/1 and C2 1/1. These are outcomes of scripted,
deterministic mock agents. They say the platform's coordination channel
changes the outcome of a task built so that it must; they say nothing about
how real coding agents behave.

I confirmed the C0 failures are the designed failures and not a bug by
running the integration test in the merged C0 workspace: `interface_consumer`
fails with `TypeError: format_price() missing 1 required positional argument:
'currency'`, `shared_utility_refactor` fails at collection with `ImportError:
cannot import name 'clean' from 'textutil'`. The tests assert the exception
type and the merged file contents, so an outcome that was right for the wrong
reason would fail them. Each fixture's untouched tests pass at baseline, so
the failure is induced by the scenario.

### How they differ from `schema_handler_widen`

Same coordination structure (disjoint ownership, a cross-agent dependency),
different mechanism, deliberately:

- `interface_consumer`: the consumer *calls* a function whose signature
  changed, so a stale consumer raises when it runs, not when a list is
  compared.
- `shared_utility_refactor`: one refactor renames a shared name and removes
  the old one; two consumers owned by two different agents import it. Three
  agents and a fan-out dependency; the stale failure is at import.

### Experiment profiles: the new tasks are held out

`causalmesh experiment plan` builds its task set from every YAML in
`tasks/` (minus `cooperbench_import`), so dropping two more tasks in would
have silently changed every existing profile: `pilot` 24 -> 48 runs, `small`
80 -> 160, `medium` 240 -> 480, and the committed pilot would stop describing
the collection it was run on. The `confirmatory` profile's 1920 figure is
`run_count(4)` in a unit test and does not read the directory, so that test is
unaffected, but the directory now holds exactly four authored tasks, so
un-gating it later would produce 1920 by coincidence rather than by an
explicit decision.

So both tasks declare `in_design: false`. `TaskDefinition.in_design`
(default `True`) is omitted from `to_dict()` when true, so every existing
task's `content_hash` is byte-for-byte unchanged (checked against the
unmodified tree: `schema_handler_widen` a9a0e7fd..., `concurrent_edit_collision`
554450aa..., `cb_tinyrepo_task1` ceeadb78...). `experiment plan|run` skips
tasks that are not `in_design`; `task list`, `task validate`, `doctor` and the
onboarding screen still show them, and `task list --json` gains an
`in_design` field. Admitting one is an explicit edit (flip the flag, bump
`version`), which changes its hash and so shows up in the plan.

### Files

- `src/causalmesh/tasks/definition.py`: `in_design` flag (strict boolean).
- `src/causalmesh/cli/commands_experiment.py`: plan filter (3 lines).
- `src/causalmesh/cli/commands_task.py`: `in_design` in `task list --json`.
- `tasks/interface_consumer.yaml`, `fixtures/pricing_interface/` (new).
- `tasks/shared_utility_refactor.yaml`, `fixtures/text_utility/` (new).
- `tests/unit/test_tasks.py` (flag), `tests/integration/test_task_families.py`
  (definition, structure, arms, mechanism, chain verification, gate, profile
  isolation), `tests/reproducibility/test_task_family_determinism.py` (same
  seed -> same `head_hash`).

`TaskFamily` already had `INTERFACE_CONSUMER` and `SHARED_UTILITY_REFACTOR`;
no new member was needed. No existing fixture was touched.

## CHANGELOG bullets

- Add the `interface_consumer` task (consumer calls a function whose
  signature changed; stale consumer fails with `TypeError`) and its
  `pricing_interface` fixture.
- Add the `shared_utility_refactor` task (one refactor removes a shared name
  that two consumers owned by two agents import; stale consumer fails with
  `ImportError`) and its `text_utility` fixture.
- Both tasks pass the section 37 sensitivity gate when run for real
  (C0 0/3, C2 3/3), with a verifiable signed chain in every arm and the same
  `head_hash` for the same seed.
- Add `TaskDefinition.in_design` (default true, omitted from the task hash
  when true). `experiment plan` and `experiment run` skip tasks that set it
  false, so adding a task no longer silently resizes `pilot`, `small` or
  `medium`. `task list --json` reports it.

## Backlog entries

Replace the body of "Remaining task families (Step 9)":

> **Status:** built. All four section 35 families now have a task:
> `schema_handler_widen`, `concurrent_edit_collision`, `interface_consumer`,
> `shared_utility_refactor`. Both new tasks passed the section 37 gate when
> run (C0 0/3, C2 3/3 over three repetitions), with mock agents.
>
> **What is still open.** The two new tasks are held out of experiment
> profiles (`in_design: false`). They have not been part of any collection,
> so no pilot or medium result covers them, and the committed pilot is still
> 2 tasks x 4 arms x 3 repetitions. Admitting them is a decision about what
> `pilot`/`small`/`medium` mean, made explicitly, not a side effect of adding
> a file.
>
> **What these tasks do not test.** Both are dependency-shaped, like
> `schema_handler_widen`: ownership is disjoint, so C3 refuses nothing and
> ties C2 on both. Only `concurrent_edit_collision` exercises enforcement.
> A shared-utility task where two agents *edit the utility itself* would be
> contested and would say something about C3; it is not built.

New entry, "`shared_utility_refactor` judges divergence on one file":

> `SuccessCriteria` holds a single `divergence_file`/`divergence_marker`. The
> task has two consumers, and the divergence check names `src/search.py`
> only. A run where just `agent_c`'s `src/exporter.py` is stale still fails,
> through the integration-test half of success, and is recorded as a test
> failure with the divergence marker absent. That is correct for the
> primary outcome but hides which consumer went stale from the divergence
> counters. Supporting a list of divergence checks changes the task schema and
> every task hash, so it was not done here.

New entry, "Scripted branches encode the answer":

> Every information effect in these tasks is a pair of guarded writes
> (`if_informed_about` / `if_uninformed_about`) written by the task's
> author. The gate therefore demonstrates that *the channel delivers the
> event and the scripted agent acts on it*, which is what section 37 asks of
> the platform. It cannot show that a real agent would act on the same
> event, and no result from these tasks should be reported as if it did.

## README / docs snippets

`README.md` status table row:

    | Task system + empirical §37 gate | ✅ 4 tasks (2 in the experiment profiles) |

`docs/tasks.md` "Status" paragraph:

> Status: describes Step 9 of `docs/PLAN.md`. Four tasks exist, one per
> section 35 family. `schema_handler_widen` and `concurrent_edit_collision`
> are scheduled by the experiment profiles; `interface_consumer` and
> `shared_utility_refactor` are listed and gate-checked but held out
> (`in_design: false`) until someone admits them.

`frontend/content/docs/operating/tasks.mdx`, replacing the heading "The two
tasks that exist" with "The tasks that exist" and appending:

    ### `interface_consumer` — dependency

    agent_a changes a function's signature; agent_b's consumer calls it. A stale
    consumer raises `TypeError` the first time it runs. C0 fails, C1 to C3 pass.

    ### `shared_utility_refactor` — dependency, fan-out

    agent_a renames a shared utility function and removes the old name; two
    consumers owned by two other agents import it. A stale consumer fails at
    import. C0 fails, C1 to C3 pass.

    Both are held out of the experiment profiles until admitted, so `pilot`
    still means what it meant when it was run.

## Not done

- No collection was run over the new tasks and none is claimed.
- Not added to `pilot`/`small`/`medium`/`confirmatory` (see above).
- No `docs/tasks.md`, README, backlog or CHANGELOG edit, per the track rules.
- The site (`frontend/`) was not touched, so `npm run types:check` was not run.
