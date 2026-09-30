### Remaining task families (Step 9): both now built

**Status:** built and gated. `interface_consumer` and
`shared_utility_refactor` exist as `tasks/*.yaml` plus new fixtures
(`fixtures/interface_consumer/`, `fixtures/shared_utility/`). No existing
fixture was touched. That makes four authored tasks, one per §35 family, plus
the synthetic CooperBench import. This fragment is meant to replace the
"Remaining task families (Step 9)" entry in `docs/backlog.md`; that file was
not edited here.

**What each task builds.** Both are dependency-shaped, like
`schema_handler_widen` and unlike `concurrent_edit_collision`: ownership is
disjoint, `contested_paths` is empty, and one agent's write can invalidate the
other's work.

| Task | agent_a (owns) | agent_b (owns, depends on) | Stale shape | Fails as |
|---|---|---|---|---|
| `interface_consumer` | `src/pricing.py`: `quote(item)` becomes `quote(item, region)`, no default | `src/cart.py`, depends on `pricing.py`, adds `receipt()` | `pricing.quote(item)` | `TypeError` at call time |
| `shared_utility_refactor` | `src/textutil.py` and `src/articles.py`: `slugify` becomes `make_slug(text, *, sep)`, old name removed, own caller migrated | `src/tags.py`, depends on `textutil.py`, adds `tag_feed_path()` | `textutil.slugify(` | `AttributeError` at call time |

The two differ in more than naming. `interface_consumer` changes an arity;
`shared_utility_refactor` renames and adds an option, and the utility has two
callers owned by different agents, so the refactorer migrates the one it owns
and can do nothing about the other. Each task's YAML header documents its
dependency and how it exists; each fixture's module docstring says why the
change is deliberately breaking.

**How the dependency exists by construction, stated plainly.** There are three
layers, and they are not equally strong.

- *Structure:* agent_b declares the provider as a dependency and agent_a writes
  it. `validate_structure` accepts both tasks with zero errors and zero
  warnings.
- *Fixture:* the change is breaking, with no default argument and no alias. A
  caller on the old shape fails the integration test.
- *Script:* agent_b's write is guarded by `if_informed_about` /
  `if_uninformed_about`, so what it writes depends on whether the channel told
  it about the provider's change. **This guard is authored, not discovered.**
  It is the same mechanism `schema_handler_widen` uses.

**Real §37 verdicts.** `check_sensitivity`, the real C0-versus-C2 gate, run
with the mock agents, `repetitions=2`:

| Task | Verdict | C0 | C2 | C0 divergences | C2 divergences |
|---|---|---|---|---|---|
| `interface_consumer` | SENSITIVE | 0/2 | 2/2 | 2 | 0 |
| `shared_utility_refactor` | SENSITIVE | 0/2 | 2/2 | 2 | 0 |

The tests pin the `repetitions=1` counts (C0 0/1, C2 1/1, divergences 1 and 0),
the same as the existing tasks' gate tests.

**All four arms, one run each, same seed:**

| Task | C0 | C1 | C2 | C3 | Coordination bytes (C0 / C1 / C2 / C3) | C3 denials |
|---|---|---|---|---|---|---|
| `interface_consumer` | fail | succeed | succeed | succeed | 0 / 372 / 199 / 199 | 0 |
| `shared_utility_refactor` | fail | succeed | succeed | succeed | 0 / 691 / 425 / 425 | 0 |

C0 fails on both criteria (tests fail and the marker remains), for the
intended reason: the failing test output in C0 is the `TypeError` or
`AttributeError` above, read from the integrated workspace rather than
inferred. C2 and C3 spend identical coordination bytes, as they must. C3 holds
a lease on every owned path and refuses nothing, because nobody writes
outside their ownership; enforcement has nothing to do on either task, which
is the same result `schema_handler_widen` gives and the opposite of
`concurrent_edit_collision`.

**A false NOT SENSITIVE the first run produced, and why it is recorded.** The
first gate run returned NOT SENSITIVE, C0 0/2 and C2 0/2, for both tasks. The
cause was the environment, not either task: the harness runs
`python -m pytest` using the `python` on `PATH`, and in that shell it had no
pytest, so the integration test exited non-zero in every arm. Divergence
counts still separated the arms (2 versus 0), but success did not. With the
venv first on `PATH` the same code returned SENSITIVE. Nothing in the task
definitions changed between the two runs. This was diagnosed and not tuned
around. It is a genuine hazard of the gate that the existing tasks share: a
missing test runner is indistinguishable from "the arms do not differ" unless
someone reads `tests_passed` and `divergence_absent` separately. It is not
fixed here.

**What the verdict is carried by.** To check that the SENSITIVE verdict is not
only the guard, the provider was rebuilt backward-compatibly (a default
argument for `quote`; `slugify = make_slug` left behind as an alias) and the
uninformed consumer was run again in C0. Its stale call shape then works: the
integration tests **pass**. The run still fails, because §38 also requires the
divergence marker to be absent and the marker is a string match on the stale
call shape. So on these tasks the verdict is carried jointly by the breaking
change and by the marker. The marker alone would call a harmless stale call a
failure. That is a property of the §38 rule as implemented, not something these
tasks introduced, and it is pinned in
`tests/integration/test_task_families.py::TestTheDependencyIsTheBreakingChange`.

**A side effect on the confirmatory plan.** `experiment plan --profile
confirmatory --allow-gated` plans every authored task in `tasks/`. It now
returns 1920 runs (120 repetitions x 4 arms x 4 tasks), matching the design the
spec names, where it returned 960 with two tasks.
`tests/integration/test_cli.py::TestPlan::test_the_gate_opens_when_asked_explicitly`
was updated from 960 to 1920 for that reason. The gate on the confirmatory
profile stays closed and nothing was executed. Only the plan grew; note that all
four tasks' C0-versus-C2 contrast comes from authored scripts, per the next
section.

**What this does not claim.**

- **Nothing about agent behaviour.** Every run used a deterministic mock agent
  whose branch is chosen by the script. SENSITIVE says the authored
  construction separates C0 from C2 when an agent acts on the information it
  gets. It does not say a real model would act on it, or would have made the
  stale call in the first place.
- **The verdicts are close to tautological by design.** The scripts write the
  stale shape when uninformed and the current shape when informed, and the
  marker detects exactly that. The gate confirms the construction is wired
  correctly (the informed channel reaches agent_b, the stale branch really
  breaks the test, the integration and marker checks agree). It is not an
  independent estimate of how often real agents would break such an interface.
- **No realism claim for the fixtures.** Both are a few dozen lines, written
  for the task. They are not drawn from real repositories.
- **No size claim.** One scripted pair per family, single seed, at most two
  repetitions. The mock is deterministic, so repetitions add no variance; they
  only confirm the result reproduces.
- **Enforcement is not shown to help or hurt here.** C3 equals C2 on both, for
  lack of any contested path. The only task that exercises the gate's refusal
  path remains `concurrent_edit_collision`.

**What it would still take:** a dependency-shaped family where the stale shape
is not a literal in the script, for example a real model writing the consumer
after an observed interface change, so that informed and uninformed behaviour
is measured rather than authored; a gate that reports a missing test runner as
"could not run" instead of as a failed arm; and a divergence rule that does not
depend on a string marker alone.
