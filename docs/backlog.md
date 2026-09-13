# Backlog

Everything this build does **not** do, recorded as a tracked item rather
than left as a silent gap. `docs/PLAN.md` commits to this: where an
implementation falls short, the documentation says so plainly.

An entry here is a deliberate scope decision with a stated reason. It is
not a to-do list of things forgotten.

## Declared non-goals for the vertical slice

These are the five items `docs/PLAN.md` names explicitly.

### Real LLM adapters (OpenAI, Anthropic, local)

**Status:** not built. `adapters/` holds the `CodingAgent` interface;
`agents/mock.py` is the only implementation.

**Why:** no API keys, no cost, no model nondeterminism. The infrastructure
claims this project makes — chain integrity, isolation, claim exclusivity,
coordination accounting — are all testable deterministically, and a
nondeterministic agent would make a failing test ambiguous between "the
harness is broken" and "the model did something else this time".

**What it would take:** an adapter implementing `CodingAgent`, plus a
decision about how to hold decoding parameters constant across arms (§3)
and how to record model version as a potential confound (§43).

**What it blocks:** every claim about *agent behaviour*. This build
measures the platform, not language models. Nothing in it supports a claim
about how real coding agents coordinate.

### CooperBench import (§54)

**Status:** not built.

**Why:** the task system (§35–38) had to exist and be proven on a task
whose coordination structure is known by construction before importing
tasks whose structure has to be discovered. `schema_handler_widen` was
built so the §37 gate could be validated against a task where the expected
answer was known.

**What it would take:** a loader mapping CooperBench tasks onto
`TaskDefinition`, and a §37 sensitivity run per imported task — most of the
cost is the gate, not the loader.

### Multi-rater kappa coding (§53)

**Status:** not built.

**Why:** §53 concerns the *secondary* qualitative coding of failure modes.
The primary outcome (§38) is deliberately free of human judgement, and it
is the only thing this slice measures.

**What it would take:** a coding scheme, at least two raters, and a kappa
computation. The raters are the hard part and the reason this is not a
code-only task.

### Scaling beyond 4 agents (§86)

**Status:** not built. `PathScopedDelivery` exists in `relay/delivery.py`
for it, and is not used by the four primary arms.

**Why:** broadcast fan-out grows quadratically with agent count, so the
scalability profile needs an interest-scoped delivery policy to stay
tractable. The policy is written; the profile, the tasks and the analysis
are not.

**Note on §92 (no dead code):** `PathScopedDelivery` is exercised by unit
tests but has no production consumer in this slice. It is a genuine
exception to the no-dead-code rule, recorded here rather than hidden.

### The 1920-run confirmatory execution

**Status:** machinery built and tested; **gate closed**.

**Why:** executing the confirmatory collection commits to a preregistered
analysis, and this project has not preregistered one. `profiles.py` marks
it `gated=True`; `profile("confirmatory")` raises unless `allow_gated=True`
is passed explicitly.

**What it would take:** a preregistration, and the compute. Not a code
change — the code is finished and `test_the_confirmatory_profile_is_the_1920_run_design`
confirms the scale.

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
is process separation rather than a filesystem jail. `docs/security.md`
states this precisely rather than claiming a jail that does not exist.

**What it would take:** running the harness on Linux or in CI, where the
container boundary is real. The three-layer model would then have a
stronger L1 without any change to L2 or L3.

### Timeout as a distinct run state (Step 10)

**Status:** `RunState.TIMED_OUT` exists in the state machine and is legal
from RUNNING; the loop never assigns it.

**Why:** command-level timeouts are handled inside the tool layer (§22),
where a hung command becomes a `CommandResult` with `timed_out=True`. A
whole-run timeout is a different mechanism — it needs a watchdog that can
interrupt an in-flight run — and this slice does not have one.

**Why the state exists anyway:** the transition table is the specification
of what a run may do. Adding the state later would mean changing a
persisted schema. It is reachable in the machine and tested there
(`test_a_failed_run_is_never_retried` covers its retry semantics), so it is
not dead code — but no run has yet reached it, and this file says so rather
than letting the state's presence imply a capability.

### Remaining task families (Step 9)

**Status:** one task exists (`schema_handler_widen`, the schema/handler
family). Three families from §35 are unbuilt: `interface_consumer`,
`shared_utility_refactor`, `concurrent_edit_collision`.

**Why:** §37 requires each task to *empirically demonstrate* its
coordination dependency, which costs a C0-versus-C2 validation run per
task. Building four tasks before validating one would have risked four
tasks with the same defect.

**Note:** `concurrent_edit_collision` is the family the §74 acceptance
criterion needs — it is the one where C3 prevents a conflicting write. The
current task has no contested path, so it exercises enforcement without
ever triggering a denial. **§74 cannot be satisfied until that family
exists**, and Step 16 depends on it.
