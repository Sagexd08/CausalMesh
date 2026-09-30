# Staleness estimators: what is needed before any can be written

**No staleness estimator is implemented, and none is approximated here.**
`docs/PLAN.md` (Step 11) names three quantities, lambda-hat, delta-hat and
Delta-hat, and the specification sections that define them (sec 23 and sec 45)
are not in this repository. `docs/backlog.md` ("Staleness estimation") records
the decision not to reconstruct them from the data: an estimator derived from
its own inputs would carry the specified symbol while possibly measuring
something else, which sec 68 exists to prevent. That decision stands. This file
does not define any of the three quantities and must not be read as doing so.

It answers two questions and nothing else:

1. What the sec 23 / sec 45 text has to say, for each estimator, before anyone
   can implement it without guessing.
2. Which observations the runs already persist, by field, so that when the
   definitions arrive the instrumentation question is already answered (and
   where it is only partly answered).

`src/causalmesh/metrics/` contains cost accounting only. `src/causalmesh/analysis/`
contains `agreement.py` (kappa coding) only. Neither computes staleness.

---

## 1. What each definition must specify

The same checklist applies to lambda-hat, delta-hat and Delta-hat. A definition
is implementable when every line has an answer in the specification text. Each
line is a question; none is answered here.

**A. The estimand**

- What real-world quantity does the symbol stand for, in words?
- What are its units (per turn, per second, per event, dimensionless)?
- Is it per agent, per path, per pair of agents, per run, per arm, per task?
- Is it a rate, a delay, a probability, a proportion, or a duration?
- How do the three symbols relate (does one feed another)? PLAN.md Step 12
  lists predicted quantities (`C_tr`, `C_md`, `rho(T)`, `T*`, `P_stale`,
  `P_floor`) that are "not built"; which of those consume these estimates, and
  which are predictions to be compared with them?

**B. The estimator**

- The formula, as a function of named inputs, with the exact inputs listed.
- Point estimate only, or with an interval; if an interval, by what method.
- Behaviour with few or zero events (a rate over zero events is not zero: this
  project's rule is "an absent field is `unknown`, never `0`"; the definition
  must say which cases yield `unknown`).
- Treatment of censoring: a run that ends, crashes or stalls before an
  observation could complete.
- Small-sample and degenerate cases (one agent, one turn, no shared path).

**C. Time base**

- Logical turn index or `timestamp_us`? Section 3 below shows why this
  matters: under the mock agent, event timestamps are synthetic.
- Which clock defines "when" a peer's write happened versus "when" another
  agent learned of it, and what resolution is required.

**D. Event and path scope**

- Which `EventType`s count as a change that can make another agent's knowledge
  stale (`WRITE`, `CREATE`, `MODIFY`, `DELETE`, `RENAME`, `CLAIM`, `RELEASE`,
  `COMMIT`, or a subset).
- Path granularity: exact file, directory prefix, or declared `owns` /
  `depends_on` sets from the task definition.
- Which agents count as observers, and whether an agent's own writes are
  excluded.

**E. What "known" and "stale" mean**

- Delivered, selected or injected? The channel keeps these apart (`events_available`
  versus `events_injected`), and the agents deliberately treat only *injected*
  events as known. The definition must say which one counts.
- Under C1 (unbounded transcript), C2/C3 (bounded window `w`) and C0 (nothing
  delivered), does the same estimator apply, and what value does C0 take: zero,
  undefined, or the no-information limit?
- Is staleness measured at the moment of an agent's action, at every turn, or
  at the end of the run?

**F. Observed versus predicted**

- PLAN.md requires "**observed** values strictly distinct from **predicted**
  curves". The definition must state how each is labelled in output, so an
  estimate can never be mistaken for a model prediction (sec 68 labels).

**G. Validation**

- Hand-computed test vectors (PLAN.md Step 12 asks for "unit-tested against
  hand-computed values"), ideally taken from the specification's own worked
  example, so an implementation is checked against the definition and not
  against itself.

**Recommended precondition:** the specification text for sec 23 and sec 45
checked in (or its relevant paragraphs), because until it is, every item above
is unanswerable from this repository.

---

## 2. Persisted observations that could feed an estimator

All of these are written by the existing run path and appear in the run
artifact (`RunResult.to_dict()` in `tasks/runner.py`) and, for events, in the
signed chain. Reading them is a matter of a loader; nothing new needs to be
recorded for the fields marked "present".

### 2.1 Events (the signed chain, `records` in the run)

`events/schema.py`, `Event`:

| Field | Meaning for an estimator |
|---|---|
| `event_id` | key that observation lists refer to |
| `identity.agent_id` | who acted (not `event.actor_id`) |
| `identity.run_id`, `identity.arm`, `identity.task_id`, `identity.experiment_id` | grouping keys |
| `event_type` | one of `EventType` (INTENT, READ, WRITE, CREATE, MODIFY, DELETE, RENAME, TEST, CLAIM, RELEASE, COMMIT, FAILURE, POLICY_VERDICT, ACCEPTANCE_DECIDED, CHECKPOINT_DECIDED) |
| `sequence` | the relay's monotonic sequence; authoritative order (`docs/backlog.md`: filesystem mtimes were rejected as the ordering source) |
| `timestamp_us` | integer microseconds; see 3.1 |
| `paths` | paths the event touches |
| `references`, `parent_id` | links between events |
| `payload` | event-specific data |

Relay totals are in `relay_summary` (`relay/core.py`, `Relay.summary`):
`sequence`, `head_hash`, `participants`, and `stats`.

### 2.2 Per-turn observations, per agent

`agent_summaries[<agent_id>]["observations"]` (`agents/mock.py`, `MockAgent.summary`):
one entry per turn, `{"turn": t, "event_ids": [...]}`, the peer events the relay
**delivered** to that agent that turn. This is the closest existing record of
"which events each agent saw and when".

`agent_summaries[<agent_id>]["informed_paths"]`: the sorted set of paths for
which the agent was **injected** with an event (the channel decision, applied by
`_was_injected`), accumulated over the whole run.

Per-turn agent state also includes `turns` (count), `crashed`, `denied`,
`failed`, `actions_executed`, `actions_scripted`, and `skipped_actions`
(`[{turn, reason}]`, which records turns where an `if_informed_about` /
`if_uninformed_about` guard changed what the agent did).

### 2.3 Coordination accounting, per agent

`agent_summaries[<agent_id>]["coordination"]` (`channels/base.py`,
`InjectionAccounting.to_dict`): `turns`, `coordination_bytes`,
`coordination_tokens`, `events_available`, `events_selected`,
`events_injected`, `events_dropped`, `received_no_coordination`, and
`turn_digests` (one SHA-256 per turn of the injected text).

### 2.4 Causal edges and claims

`edges` (`edges/types.py`, `CausalEdge`): typed relationships between events,
of type `CAUSED`, `REQUIRED`, `RECOVERED`, `SUPERSEDED`. `claim_history` and
`denials` record lease acquisition and refusals. `boundary_summaries` and
`gate` record lifecycle-boundary and gate activity.

### 2.5 Task shape

The task definition (`tasks/definition.py`) declares each role's `owns` and
`depends_on` paths and the task's `contested_paths`. These define which paths
are shared and which agent depends on which.

### 2.6 Outcome

`outcome.succeeded`, `outcome.tests_passed`, `outcome.divergence_absent`,
`outcome.evidence` (`tasks/outcome.py`), so any staleness measure can be related
to whether the run succeeded, with `unknown` handled as
`metrics/accounting.py` already does.

---

## 3. Gaps and wrinkles found while reading the fields

These matter to the definitions and are listed so they are not discovered
mid-implementation. None is fixed here.

**3.1 Mock timestamps are synthetic.** `tasks/runner.py` builds each turn's
context with `now_us = base_time_us + turn * tick_us` (defaults
`1_700_000_000_000_000` and `1_000_000`), and the tool executor stamps events
with that `now_us`. Under the mock agent, `timestamp_us` is therefore a logical
clock (one second per turn), not elapsed time. A time-based estimator would
measure the schedule, not the system, unless the definition is stated in turns
or real-model runs supply wall-clock time. Which is meant is a definitional
question (section 1C).

**3.2 The observations key differs between agent kinds.** The scripted agent
writes `{"turn", "event_ids"}`; the model-backed agent
(`adapters/model_agent.py`) writes `{"turn", "events"}`. A loader must accept
both, or one of them should be aligned. Reading only one key would silently
report no observations for the other kind of run: the confident-zero failure
mode this project has recorded before.

**3.3 Per-turn injection counts are not persisted individually.**
`Injection` (the per-turn object carrying `events_available`, `events_selected`,
`events_injected`, `events_dropped` and `selection_reasons`) is transient;
`InjectionAccounting.record` keeps only running totals plus one digest per
turn. What survives per turn is the delivered event ids (2.2) and a digest of
the injected text. Per-turn `events_injected` and which delivered events were
dropped by the window can be reconstructed only by re-deriving the channel's
selection, which is exactly the "reconstruct rather than record" pattern the
metrics module avoids. If a definition needs per-turn injected versus dropped,
the instrumentation is **not** already persisted and would need adding
(recorded here as a gap, not built).

**3.4 `informed_paths` is a final set, not a history.** It shows what an agent
was told by the end, not when it learned each path.

**3.5 Real-model runs are not part of the collection path.** `execute_task`
constructs only `MockAgent`, so the model agent's `turn_records` (token counts,
protocol and transport failures) are not produced by any current run, though
the format exists.

**3.6 Repetition determinism.** With the deterministic mock agent, repeated
runs of one (task, arm) cell may yield identical observations
(`docs/preregistration-draft.md`, 1.6). An estimator's variance across
repetitions would then be zero for reasons unrelated to staleness; the
definition should say what uncertainty statement is meaningful.

---

## 4. Explicit statement

- No lambda-hat, delta-hat or Delta-hat is implemented in this repository.
- None is approximated, prototyped or stubbed behind a plausible formula.
- The `causalmesh analyze` tables that exist report cost and outcome by arm,
  labelled PILOT and DERIVED; they contain no staleness figure.
- The unblocking input is the text of sec 23 and sec 45. With it, section 1
  becomes a reading checklist; without it, any implementation would be a guess
  carrying the specified symbol.
