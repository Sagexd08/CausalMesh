# Fragment: scaling beyond four agents (track SCALING)

For the integrator to fold into CHANGELOG.md, docs/backlog.md, README.md and
the docs. Nothing outside `src/`, `tests/` and this file was edited.

## Summary

Broadcast fan-out grows quadratically with agent count, and the interest-scoped
policy written for that (`PathScopedDelivery`) had no caller. This change makes
delivery a per-run choice, adds a generated N-agent task, and adds a non-gated
`scalability` profile that runs for real (scripted mock agents) and reports
delivered events and coordination bytes for broadcast against path-scoped
delivery at N = 4, 8, 16.

- `relay/delivery.py`: `policy_for_arm(arm, *, mode=None, interests=None)`.
  `mode` is `"broadcast"` or `"path_scoped"`; unset is broadcast, so every
  existing caller is unchanged. C0 is `NullDelivery` whatever the mode.
  `path_scoped` without an interest map raises instead of falling back to
  broadcast. New constants `BROADCAST`, `PATH_SCOPED`, `DELIVERY_MODES`.
- `tasks/runner.py`: `RunConfig.delivery_mode` (default `None`). It is added to
  `RunConfig.to_dict()` only when set, so an unset run serialises exactly as
  before. `execute_task` builds interests from the task's roles
  (`owns | depends_on`). This is the one edit outside the track's directories
  (`tasks/`); it is small (about 20 lines).
- `tasks/scaled.py`: `ScaledSpec(n_agents, group_size=4, own_files=2)` and
  `generate_scaled_task`. Each agent owns a directory; agents are grouped, and
  each group contests one shared registry file. Deterministic, validated by
  `validate_structure`, family `concurrent_edit_collision`. Nothing is added to
  `tasks/` or `fixtures/`: the fixture is written to a scratch directory per
  run, so no existing plan, hash or run count changes.
- `experiments/scalability.py`: `ScalabilityProfile`, `scalability` (N in
  {4, 8, 16} x broadcast/path_scoped x C1/C2 x localized/dense = 24 runs) and
  `scalability_smoke` (4 runs). Kept out of `PROFILES` on purpose:
  `plan_experiment` multiplies tasks by arms by repetitions, and a profile of a
  different shape there would either change existing run counts or make
  `Profile` mean two things. `profile("scalability")` now says where it runs.
- `metrics/scaling.py`: `ScalingRun`, `growth_exponent` (log-log slope, `None`
  when undefined, never 0), `summarize_scaling`.
- `tasks/scalability.py`: `run_scalability`, `measure_run` (verifies the chain
  offline for every run), `render_scalability` (ASCII).
- CLI: `causalmesh experiment scalability [--profile scalability|scalability_smoke]
  [--seed S] [--json]`. Runs in a temp directory, writes nothing to the repo.
  Small addition to `cli/commands_experiment.py`.

Nothing about the four primary arms, `PROFILES`, `PROFILE_NAMES`, any profile's
`run_count`, the 1920-run confirmatory design, `plan_experiment`, or the
scheduler changed. `scheduler/*` and `events/schema.py` were not touched.

**Does `PathScopedDelivery` now have a production consumer?** Yes:
`tasks.runner.execute_task` installs it through `policy_for_arm` when a run is
configured with `delivery_mode="path_scoped"`, and that path is reached by
`causalmesh experiment scalability`. It is still not used by C0 to C3 as run by
`causalmesh experiment run`, whose delivery stays broadcast. So the "no
production consumer" exception is retired, but the policy is only consumed by
the scalability profile, not by the primary design.

## Measured numbers (this machine, scripted mock agents)

Produced by `causalmesh experiment scalability --profile scalability` on the
machine that ran this track (Windows 11, one run, about 35 s wall). Deterministic
for a given seed. These are properties of one generated scripted task; they say
nothing about how real agents would coordinate.

`available` is what broadcast would offer (agent events x (N-1)); `delivered`
is what agents drained from their inboxes; `unseen` is delivered but never
placed in an agent's context (metadata channel only; unknown for C1, whose
injection counter is replay volume). Each agent produces 6 events.

```
arm  topology  mode          N available delivered  ratio unseen     bytes bytes/agent   ok chain
C1   dense     broadcast     4        72        72   1.00 unknown     36702      9175.5  yes    ok
C1   dense     broadcast     8       336       336   1.00 unknown    402662     50332.8  yes    ok
C1   dense     broadcast    16      1440      1440   1.00 unknown   3719094    232443.4  yes    ok
C1   dense     path_scoped   4        72        24   0.33 unknown      7222      1805.5  yes    ok
C1   dense     path_scoped   8       336       112   0.33 unknown     79742      9967.8  yes    ok
C1   dense     path_scoped  16      1440       480   0.33 unknown    739918     46244.9  yes    ok
C1   localized broadcast     4        72        72   1.00 unknown     36702      9175.5  yes    ok
C1   localized broadcast     8       336       336   1.00 unknown    391099     48887.4  yes    ok
C1   localized broadcast    16      1440      1440   1.00 unknown   3559797    222487.3  yes    ok
C1   localized path_scoped   4        72        24   0.33 unknown      7222      1805.5  yes    ok
C1   localized path_scoped   8       336        48   0.14 unknown     32395      4049.4  yes    ok
C1   localized path_scoped  16      1440        96   0.07 unknown    136597      8537.3  yes    ok
C2   dense     broadcast     4        72        72   1.00      0      5761      1440.2  yes    ok
C2   dense     broadcast     8       336       336   1.00      0     27197      3399.6  yes    ok
C2   dense     broadcast    16      1440      1440   1.00    460     80053      5003.3  yes    ok
C2   dense     path_scoped   4        72        24   0.33      0      1943       485.8  yes    ok
C2   dense     path_scoped   8       336       112   0.33      0      9267      1158.4  yes    ok
C2   dense     path_scoped  16      1440       480   0.33     29     37680      2355.0  yes    ok
C2   localized broadcast     4        72        72   1.00      0      5761      1440.2  yes    ok
C2   localized broadcast     8       336       336   1.00      0     27197      3399.6  yes    ok
C2   localized broadcast    16      1440      1440   1.00    484     77211      4825.7  yes    ok
C2   localized path_scoped   4        72        24   0.33      0      1943       485.8  yes    ok
C2   localized path_scoped   8       336        48   0.14      0      3886       485.8  yes    ok
C2   localized path_scoped  16      1440        96   0.07      0      7772       485.8  yes    ok

growth exponent of a cost against N (1 = linear, 2 = quadratic):
  C1 dense     broadcast   delivered 2.16  bytes 3.33
  C1 dense     path_scoped delivered 2.16  bytes 3.34
  C1 localized broadcast   delivered 2.16  bytes 3.30
  C1 localized path_scoped delivered 1.00  bytes 2.12
  C2 dense     broadcast   delivered 2.16  bytes 1.90
  C2 dense     path_scoped delivered 2.16  bytes 2.14
  C2 localized broadcast   delivered 2.16  bytes 1.87
  C2 localized path_scoped delivered 1.00  bytes 1.00
```

How to read it, and what not to conclude:

- Broadcast delivered events are exactly 6 N (N-1): 72, 336, 1440. The fitted
  exponent over N = 4..16 is 2.16 (a little above 2 because N(N-1) is not a pure
  power; it tends to 2).
- With localized contention (each shared path contested by 4 agents however
  large N is), path-scoped delivery is exactly 6 N: 24, 48, 96, exponent 1.00.
  At N = 16 that is 96 of 1440 events (6.7%). This is a property of the
  topology the generator was told to build: it assumes each agent's neighbourhood
  stays small as N grows.
- With dense contention (every agent contests one path) path-scoped delivery
  removes a constant one third (the events on private files) and the growth
  order is unchanged (2.16). Scoping only helps as far as interests are
  actually narrow.
- Bytes are not a clean power law. C1 (transcript) replays a shared room, so its
  bytes grow faster than events (exponent about 3.3 under broadcast). C2
  (metadata, window 8) caps bytes per turn, so broadcast bytes grow about 1.9
  and path-scoped bytes about 1.0 under localized contention. At N = 16 the C2
  broadcast run delivered 484 events an agent never saw (the window cut them);
  the localized path-scoped run left none unseen (dense left 29).
- All 24 chains verified offline. The scripted task succeeded in all 24 runs, so
  under this task path-scoped agents were told what they needed. That is a
  statement about a scripted task where interests were declared to match the
  work, not about interest maps in general: a wrong map would silently starve
  an agent, and nothing here measures how often maps are wrong.
- Two agent counts cannot show a rate and three is a coarse fit; the points are
  printed next to the exponents for that reason. The mock agents have no
  randomness, so one run per cell is complete; a repeat gives the same head
  hash.

## CHANGELOG bullets

Under Unreleased:

- Added: selectable delivery per run. `policy_for_arm(arm, mode=..., interests=...)`
  and `RunConfig.delivery_mode` choose broadcast or path-scoped delivery for the
  informed arms. Unset behaves as before; C0 stays isolated whatever the mode.
- Added: `PathScopedDelivery` now has a production consumer (the scalability
  profile).
- Added: `tasks.scaled`, a deterministic generated task for N agents
  (`ScaledSpec`, `generate_scaled_task`).
- Added: a non-gated `scalability` profile (N in {4, 8, 16}) and
  `causalmesh experiment scalability`, reporting delivered events and
  coordination bytes for broadcast against path-scoped delivery. Scripted mock
  agents only.
- Added: `metrics.scaling` (`growth_exponent`, `summarize_scaling`); the exponent
  is `None` when undefined.
- Changed: `profile("scalability")` in the run planner now points to
  `causalmesh experiment scalability`. No profile, run count or hash changed.

## Backlog entries

Replace the "Scaling beyond 4 agents (§86)" section with:

> ### Scaling beyond 4 agents (§86)
>
> **Status:** partly built. Delivery mode is selectable per run
> (`policy_for_arm(..., mode=...)`, `RunConfig.delivery_mode`), the N-agent task
> is generated (`tasks/scaled.py`), and `causalmesh experiment scalability`
> measures delivered events and coordination bytes at N = 4, 8, 16 for broadcast
> against path-scoped delivery, on scripted mock agents. `PathScopedDelivery` is
> consumed by that path, so the §92 dead-code exception is retired.
>
> **What is not built:**
> - the profile is not part of `causalmesh experiment run` or the scheduler: it
>   is measured, not planned, randomized, indexed or resumed, and it writes no
>   run artifacts under `data/raw`. Reason: it has no repetitions or tasks to
>   randomize, and the scheduler track owns `scheduler/*`.
> - interests are declared by the harness and match the scripted work exactly.
>   How wrong an interest map has to be before an agent is starved, and how
>   agents should declare interests in practice, is unmeasured.
> - one topology family only (contention groups of fixed size, or one dense
>   group). No chains, rings, hub-and-spoke, or interest overlap between groups.
> - only N up to 16 was run (the generator accepts up to 99). Beyond 16 the
>   exponent is extrapolation.
> - path-less events (list, test, intent, acceptance) are delivered to everyone
>   by `PathScopedDelivery`; the profile's task emits none from agents, so the
>   cost of scoping those is unmeasured.
> - the growth statement is over delivery and channel bytes, not tokens billed,
>   latency, or task quality; C3 (claims) is not in the default profile
>   (one ad hoc C3 run at N = 8, path-scoped, failed the integration test: the
>   shared registries are contested, so the exclusive leases refuse the
>   non-owner writers. One run, not a result.)
> - the C1 transcript `Room` appends a message for every delivery, so N-1
>   copies of each event enter the room under broadcast. That inflates C1 bytes
>   beyond what one transcript per event would cost; it predates this change and
>   is not corrected here.
>
> **Note on the C2 channel counter:** `MetadataChannel` re-counts its carried-over
> backlog into `events_available` on every turn, so summing that field across
> turns exceeds what the relay delivered (this profile found a 1440-event run
> reporting 3826). The profile counts what agents drained instead. The channel
> counter is left as is because existing analysis reads it, but it should not be
> read as a delivery count.

## README / docs snippets

README (Scaling section, one paragraph):

> Broadcast delivery scales as N(N-1): in a scripted 16-agent run every agent
> receives every peer event (1440 deliveries against 96 when delivery is scoped
> to declared paths). `causalmesh experiment scalability` reproduces these
> numbers on your machine with mock agents; they describe delivery cost, not
> agent behaviour.

docs/protocol.md, after the arm/policy table:

> The informed arms can be run with path-scoped delivery instead of broadcast
> (`policy_for_arm(arm, mode="path_scoped", interests=...)`, or
> `RunConfig.delivery_mode`). This is used by the scalability profile only; the
> four primary arms are broadcast. C0 is `NullDelivery` in every mode.
> Path-scoped delivery hands an agent exactly the events whose paths intersect
> its declared interests, and every path-less event to everyone.

docs/tasks.md:

> `causalmesh.tasks.scaled` generates a task for N agents from `ScaledSpec`
> (agents, contention group size, files per agent). The task and its fixture
> are produced in memory and in a scratch directory; nothing is added to
> `tasks/` or `fixtures/`, so it is not part of any run plan.

CLI docs:

> `causalmesh experiment scalability [--profile scalability_smoke|scalability] [--json]`
> runs the scalability profile in a temp directory and prints delivered events
> and coordination bytes by agent count and delivery mode. `scalability_smoke`
> takes a few seconds; `scalability` (24 runs) about half a minute.

## Notes for the integrator

- Editable install: `python -c "import causalmesh"` from a worktree can resolve
  to the main checkout's `src` (this happened here). pytest is unaffected
  because `pyproject.toml` sets `pythonpath = src`, but ad-hoc scripts need
  `PYTHONPATH=src`.
- `tests/reproducibility/test_collection_determinism.py::test_two_collections_produce_identical_chains`
  failed once under `-n 2` alongside other suites and passed on every rerun,
  alone and in the same combination. Not reproduced; noted rather than
  explained.
- Files touched outside the track's directories: `src/causalmesh/tasks/runner.py`
  (RunConfig field and policy call), `src/causalmesh/cli/commands_experiment.py`
  (one new command), `src/causalmesh/experiments/profiles.py` (error hint).
