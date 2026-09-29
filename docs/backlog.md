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
financial audit layer, not a payment SDK.

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
approval queue, anything with actual I/O) is left to whoever wires one in;
none is built here, because that is an operator integration, not a contract
mechanic.

**On the chain.** A matched checkpoint decision is signed and recorded as
`EventType.CHECKPOINT_DECIDED`, under a dedicated `checkpoint` identity —
distinct from `policy_gate`'s, the same way `ACCEPTANCE_DECIDED` already gets
its own `acceptance` identity, because a checkpoint decision is not itself
one of the gate's ordinary rule verdicts even though it reaches the chain
through the same `gate.verdicts` list.

**What this does not do.** No real human-attached `CheckpointHandler` ships
here — only the mechanism and the two reference implementations
(auto-deny, scripted). Nothing in the CLI surfaces a pending checkpoint or
prompts an operator; wiring a terminal-facing handler into `causalmesh
experiment run` is separate, follow-on work.

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
`RunState.TIMED_OUT` is declared before anything assigns it. **What it would still
take:** wiring the Jev adapter in as a `Choice` call among the three verdicts, which
needs a decision that is genuinely uncertain given current state — this rule isn't
one, by design (see "Adapter built, not wired" below).

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

**Status: population started.** Store and query surface built and tested
(`src/causalmesh/edges/`, `tests/unit/test_edges.py`, 25 tests). `execute_task`
(`tasks/runner.py`) now populates one real relationship: a `REQUIRED` `CausalEdge`
from a denied write's `FAILURE` event back to the `POLICY_VERDICT` event that refused
it, recorded on `RunResult.edges` (and therefore in the run artifact, alongside
`chain`) whenever a contract is installed and refuses at least one call.
`tests/integration/test_task_execution.py::TestCausalEdgesForDenials` proves it end to
end: every denied write in the scenario gets exactly one edge, pointing at a real
verdict event that is itself a refusal.

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

**What it would take (remaining):**

- *More population sources.* Only the denial-to-verdict relationship is populated.
  The acceptance decision (`ACCEPTANCE_DECIDED`, see "Explicit acceptance decision
  object" below) has no edge back to the evidence it was decided from, because there
  is no chain event yet representing "the integration test that decided this run" —
  `evaluate_outcome` runs directly on the integrated workspace, outside the chain.
  Fabricating an edge to a synthetic id would misrepresent evidence; the honest fix
  needs that test result to become a real chain event first, which this pass did not
  attempt.
- *A query-facing surface.* `EdgeIndex` (in-process) exists; a `causalmesh`-CLI-facing
  view (e.g. `causalmesh analyze --edges`, following the existing command's `--json`
  and PILOT/DERIVED labeling conventions) does not.

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
  `causalmesh serve` — only the four runtime dependencies (`cryptography`,
  `PyYAML`, `typer`, `rich`; `serve` itself uses only `http.server` from the
  stdlib), no `causalmesh.yaml` baked into the image, bind-mounted read-only at
  run time instead. Verified by hand in this environment (Docker Desktop's
  daemon was not running by default; started for this check): `docker build`
  succeeds, `docker compose up` starts the container, `GET /healthz` returns
  200, and a `POST /v1/chat/completions` against this repository's own
  `causalmesh.yaml` (no `--upstream`, so a stub reply) returns a gated response
  rather than a connection error.

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
a regression this work introduced. Fixing it (either pin `click`, or have the
two `TestQuickstartEndToEnd` tests assert against `result.output` /
`result.stderr` instead of `result.stdout`) is real, scoped, unstarted work,
recorded here rather than patched silently alongside an unrelated feature.
  and PILOT/DERIVED labeling conventions) does not.
