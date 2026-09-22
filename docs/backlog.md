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

## The policy plane (built 2026-09-15, not yet wired)

`docs/policy.md` describes a contract, a gate and a ledger that generalise
enforcement from file paths to resources of four kinds — paths, spend,
endpoints and budgets. 38 tests cover it and `causalmesh policy check`
interrogates it. These are the gaps it has, recorded before anyone has to
discover them.

### The gate is installable but not yet installed by default

**Status (updated again):** `ContractGate` in `hooks/policy_gate.py` satisfies the
same `Gate` protocol the arms already install, so the lifecycle boundary takes it
without a new code path. It is covered by 12 tests, and — as of the change recorded
under "Verdicts do not enter the signed chain" below — every verdict it reaches now
becomes a signed chain event when it is installed. What remains is that no arm or
profile selects it: a default run still installs `ClaimGate`.

**Why the arms do not use it.** The experiment's contrast is C2 against C3,
and that is only clean if the two arms differ by one factor. `ClaimGate` is
that factor. A gate that also refuses on ownership would be a second
difference, and the C2 to C3 contrast would stop isolating enforcement. So
the narrow gate stays the arms', and the contract gate is what an operator
installs when running work rather than running an experiment.

**What it still blocks:** a run driven by `causalmesh.yaml` end to end. The
gate decides correctly and records its refusals; nothing yet hands it to a
scheduler and writes its verdicts into the run artifact.

**A bug this found in itself.** The first version returned a lease refusal
without recording a denial, because the policy gate consults leases through
`may_write`, which deliberately records nothing. That is the same defect
recorded below under "Enforcement was unmeasurable, not merely unmeasured".
It was caught by its own test rather than by a run, which is the outcome the
discipline is for.

### Spend is enforced, but nothing speaks x402

**Status:** `spend` resources pass through allowlists, per-call ceilings and
totals, with exact decimal arithmetic. No adapter obtains one from an
`HTTP 402` response.

**What it would take:** a client that reads the 402 challenge, forms a
`Resource.spend`, asks the gate, and only then pays. The gate half is done;
the protocol half is not started.

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

### Checkpoints and identity are parsed and ignored

`policy.checkpoints` (human-in-the-loop) and `identity` (per-agent keys) are
accepted by the contract parser and read by nothing. They are in the schema
because the shape is known and leaving them out would force a version bump
later; they are listed here because a key that parses and does nothing is
exactly the silent gap this file exists to prevent.

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

**Status:** two tasks exist — `schema_handler_widen` (schema/handler) and
`concurrent_edit_collision` (contested path). Two families from §35 remain
unbuilt: `interface_consumer` and `shared_utility_refactor`.

**Why:** §37 requires each task to *empirically demonstrate* its
coordination dependency, which costs a C0-versus-C2 validation run per
task. Building four tasks before validating one would have risked four
tasks with the same defect.

**Resolved (Phase 0):** `concurrent_edit_collision` now exists and a real
C3 run records a denial with actor, path and holder. Building it exposed
that the denial log had never been reachable from the gate at all — see
below.

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

**Status:** not built. Run success today is read directly off `SuccessCriteria` and
the verifier's result — a pass/fail, not a named decision.

**Why:** an explicit `ACCEPT` / `REJECT` / `HUMAN_REVIEW` record, entered into the
chain as its own event distinct from the verification result it was based on, makes
"why was this run accepted" a recorded decision rather than something reconstructed by
re-reading the verifier's output. This also needs a task whose acceptance is genuinely
contestable — a contested-path task, which §74 (the acceptance blocker recorded
elsewhere) notes does not exist yet — before the decision is meaningful to test rather
than trivially always-ACCEPT.

**What it would take:** a contested-path task (blocking), then a new chain event type
(`acceptance.decided`, say) carrying the verdict, the evidence it was based on, and —
once the Jev adapter has a wiring target — optionally a Jev `Choice` call among
`ACCEPT`/`REJECT`/`HUMAN_REVIEW` rather than a hand-written threshold rule.

### Agent handoff package on recovery

**Status:** not built, and currently has no design target: the scheduler
(`scheduler/states.py`, `scheduler/loop.py`) runs exactly one agent per run, with no
transition for "hand off to a different agent mid-run." `recover` as a decision type —
retry the same agent, switch agents, or escalate — presupposes that transition exists.

**Why deferred:** multi-agent recovery is a bigger change than an adapter or a doc
addition — it means a new run state, a new chain event class, and a decision about
what a second agent inherits (task, repository state, diff so far, test results, prior
decisions) so it starts from where the first agent left off rather than cold. Building
the handoff format before the state machine that would use it exists would be
designing against a system that does not yet have the shape the design assumes.

**What it would take:** first, a scheduler state for "run continues under a different
agent" (an addition to `RunState`/`TRANSITIONS` in `scheduler/states.py`); then a
handoff record shape; then, once that exists, `recover` becomes the concrete decision
point the Jev adapter above was built for.

### Causal edges over the chain

**Status:** not built. The chain (`relay/`) gives total order and hash linkage today —
event N's hash depends on event N-1's — which proves *sequence* but does not record
*relationships*. "Which decision caused this write" requires reading the chain in
order and matching timestamps by eye.

**Why:** a typed relationship layer (`caused`, `required`, `recovered`, `superseded`,
...) over the existing chain would make that a query instead of a manual scan, and
would let a future audit view answer "which decision caused this write" or "which
verification evidence caused acceptance" directly. It is additive to the existing
chain — it does not change what is signed or how verification works — which is why it
is scoped as a separate layer rather than a change to `relay/`'s core hashing.

**What it would take:** a store for `(from_event_id, to_event_id, relationship)`
triples, populated as decisions and events reference each other, plus a query surface.
Not blocked on anything else in this list — it could be built against the chain as it
exists today — but was out of scope for this session, which was adapter-and-docs only.
