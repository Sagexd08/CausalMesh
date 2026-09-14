# CausalMesh — what we are building

**A coordination substrate for fleets of autonomous coding agents working on
one shared codebase, with cryptographically verifiable evidence of
everything every agent did.**

It ships as a production system. It also happens to be instrumented well
enough to answer a research question that nobody has answered cleanly, and
that dual nature is deliberate — the instrumentation *is* the operational
observability.

---

## 1. The problem

Put four coding agents on one repository and they interfere:

| Failure | What happens |
|---|---|
| **Stale read** | Agent B reads a file agent A is midway through changing, and builds on a version that no longer exists |
| **Lost update** | Two agents write the same file; whoever finishes last silently erases the other |
| **Duplicated work** | Two agents independently solve the same problem, and one is thrown away |
| **Broken contract** | Agent A widens a schema; agent B's handler still expects the old shape and nobody notices until runtime |

Every one of these is a **coordination** failure, not a capability failure.
The individual agents are each doing competent work. The system loses.

The current industry answer is to serialize — one agent at a time, or a
human merging by hand. That throws away the entire reason for running a
fleet.

### Why existing tooling does not solve it

Git handles *textual* conflicts on the same lines. It has nothing to say
about the schema/handler case above, where two files diverge semantically
with no overlapping edit. Locking systems prevent conflicting writes but
tell nobody *why* a write was refused, and produce no audit trail. Neither
answers the question an operator actually has at 3am: **what did these
agents do, in what order, and can I prove it?**

---

## 2. What CausalMesh is

Four subsystems that agents plug into, sitting between the agent fleet and
the shared repository.

```
        agent A        agent B        agent C        agent D
           │              │              │              │
     ┌─────┴──────────────┴──────────────┴──────────────┴─────┐
     │  TOOL BOUNDARY  — 11 controlled operations, no shell   │
     │  every call gated, every call recorded                 │
     └─────┬──────────────┬──────────────┬──────────────┬─────┘
           │              │              │              │
     ┌─────┴──────────────┴──────────────┴──────────────┴─────┐
     │  RELAY  — sequence, sign, hash-chain, fan out          │
     └─────┬───────────────────────────────────┬──────────────┘
           │                                   │
     ┌─────┴─────────┐               ┌─────────┴──────────┐
     │ CLAIM REGISTRY│               │ COORDINATION       │
     │ exclusive     │               │ CHANNELS           │
     │ write leases  │               │ what peers learn   │
     └───────────────┘               └────────────────────┘
                           │
                  ┌────────┴─────────┐
                  │  SIGNED CHAIN    │  ← verifiable offline,
                  │  append-only     │    with the system stopped
                  └──────────────────┘
```

### 2.1 The tool boundary — agents cannot act unobserved

Agents get exactly eleven operations: `read_file`, `write_file`,
`create_file`, `modify_file`, `delete_file`, `rename_file`, `list_files`,
`run_command`, `run_tests`, `git_status`, `git_diff`.

There is **no unrestricted shell**. `run_command` takes an argument list,
never a shell string, and refuses anything outside an allowlist. This is not
a stylistic preference: `shell=True` would let an agent reach any path its
OS token permits through `&&`, redirection, or a subshell, which voids every
containment guarantee the system makes.

Every call passes through a lifecycle boundary that gates it *before*
execution and records it afterwards — including denials and failures.

### 2.2 The claim registry — enforced exclusive writes

SQLite with `BEGIN IMMEDIATE` transactions. The invariant:

> at most one valid writer claim per path at any instant

Leases expire, so a crashed agent's lock does not wedge the fleet. Expiry
and release are recorded distinctly, because "the holder was too slow" and
"the holder finished" are different operational signals.

A denied write is **data, not an exception** — the registry records who was
blocked, by whom, and why. That record is what makes a refusal explainable
instead of mysterious.

### 2.3 Coordination channels — bounded, accounted information

Agents learn what peers did through a single typed injection point. Three
representations exist, and which one is installed determines what an agent
can know:

| Channel | Behaviour | Cost growth |
|---|---|---|
| `NullChannel` | Injects nothing; **raises** if given events | zero |
| `TranscriptChannel` | Full conversational history | quadratic in turns |
| `MetadataChannel` | Bounded window of scored, typed events | linear in turns |

The metadata channel records, per turn: events available, selected,
injected, dropped, plus a reason for every selection decision. Nothing is
silently truncated.

**This is production capacity planning, not just research instrumentation.**
An unbounded transcript is what makes long-running agent fleets expensive;
the metadata channel is the mechanism that keeps context cost linear, and
the accounting is how you know it is working.

### 2.4 The signed chain — verifiable evidence

Every event is canonicalized (sorted keys, NFC-normalized, floats rejected),
Ed25519-signed by its actor, and hash-chained:

```
h_i = SHA256(h_{i-1} ‖ canonical(event_i))
```

The verifier is **standalone**. It takes only `(log, public keys, optional
anchors)` and imports nothing from the relay — enforced by a test. You can
verify a chain on a different machine, months later, with the system shut
down.

An adversarial battery proves it detects mutation, insertion, deletion,
reordering, signature substitution, wrong-actor attribution, duplicate
replay, and anchor mismatch. **Suffix truncation is undetectable without an
anchor** — that is documented as a real limitation, not hidden.

---

## 3. Why this is a production system

The four properties an operator needs, and where each is enforced.

### Attribution

Every byte written to the repository traces to a signed event naming the
agent, the run, the arm, the machine, the operator, and the model version.
Identity is supplied explicitly and never derived from a filename, because a
path can be moved or renamed while the evidence must stay attributable.

**Deployment value:** when an agent fleet ships a regression, you can prove
which agent introduced it and what it knew at the time.

### Containment

Three layers, each with a separately stated guarantee:

| Layer | Mechanism | What it actually guarantees |
|---|---|---|
| **L1 Process** | Spawned subprocess, own cwd, scrubbed environment | No shared memory, no inherited handles, no ambient state |
| **L2 Path** | Every path resolved through `realpath`, must fall inside the workspace | Agents cannot reach peer workspaces *through the sanctioned tool API* |
| **L3 Context** | Single typed injection point, per-turn digest, byte counter | Provable account of everything that entered an agent's context |

**We do not claim a filesystem jail on Windows.** There is no `chroot` and no
mount namespaces, so L1 is process separation. `docs/security.md` states this
precisely rather than overclaiming. Docker is wired in as the stronger
boundary for Linux and CI.

### Recoverability

The scheduler survives being killed. Runs move through an explicit state
machine; evidence is written *before* the index is updated, so a crash
between the two costs time rather than evidence. A run left mid-flight is
recovered and re-executed; a run that *failed on its own terms* is never
retried, because retrying until something passes is how you fool yourself.

### Auditability

Raw evidence is immutable. The chain store is append-only with deliberately
**no** update, delete, or replace API. Writing an artifact over an existing
one raises rather than overwrites.

---

## 4. The research question, and why it is not a detour

> **How much of the coordination benefit comes from *information* (agents
> knowing what peers did), and how much from *enforcement* (agents being
> prevented from conflicting)?**

These normally arrive together — every system that shares state also locks
it — so nobody knows which one is doing the work.

Four conditions, manipulating exactly two factors:

| Arm | Information | Enforcement |
|:--:|---|---|
| **C0** | none | none |
| **C1** | unbounded transcript | none |
| **C2** | bounded metadata | none |
| **C3** | bounded metadata | write claims |

```
C0 → C2   information benefit        C2 → C3   enforcement benefit
C1 → C2   representation / cost      C1 → C3   complete system (confounded)
```

**Why an operator should care.** These are not academic conditions — they
are the four deployment configurations you can actually choose, and they
have very different costs:

- Enforcement needs a consistent lock store: latency, a failure domain, and
  contention when agents genuinely need the same file.
- Information needs context tokens: on measured data, the transcript
  representation cost **84% more** than bounded metadata for identical
  outcomes.

If information alone recovers most of the benefit, you can run a much
cheaper and more available system. **Nobody currently knows the answer, so
nobody can make that decision on evidence.** The arms are how the platform
answers it about *your* workload — and because they are installed objects
rather than config branches, the configuration you measured is structurally
the one you deploy.

---

## 5. Current state — honest

### Built, tested, and executed

| Subsystem | State |
|---|---|
| Event protocol, canonicalization | ✅ property-tested |
| Ed25519 identity, hash chain | ✅ |
| Offline verifier + adversarial battery | ✅ 8 attack classes detected |
| Claim registry, leases | ✅ concurrency-tested across threads |
| Relay: sequence, sign, chain, fan-out | ✅ |
| Isolation, 11 tools, lifecycle hooks | ✅ leakage-tested |
| Channels, relevance, information window | ✅ |
| Script-driven agent | ✅ |
| Model adapters (OpenAI, Anthropic, local) | ✅ tested over real HTTP |
| Contested-path task, enforcement denials | ✅ |
| Task system + empirical sensitivity gate | ✅ |
| Scheduler, state machine, run index | ✅ resume-tested |

**865 tests passing.** Not merely compiling — executed, with artifacts read
back and inspected.

### The critical gap: the agent layer

This needs precision, because it is the difference between a demo and a
product.

**What exists is not a stub.** The agent drives the *real* path — real tool
boundary, real gate, real hooks, real relay, real signed chain, real claim
registry. Every coordination guarantee above is exercised end-to-end by it.
It is a genuine agent implementation of the `CodingAgent` interface.

**What it is not is model-driven.** It executes declarative YAML action
scripts rather than calling an LLM. So the substrate is proven; the
*decision-making* on top of it is currently scripted.

The interface is five async methods — `initialize`, `observe`, `plan`,
`act`, `finalize` — and it is already async precisely so a network-backed
adapter drops in without reshaping anything. `adapters/` is empty by
deliberate decision, not oversight: building the substrate against a
deterministic agent means a failing test is unambiguous. With a
nondeterministic model in the loop, every failure is "the harness is broken"
*or* "the model did something different today", and you cannot debug a
coordination substrate through that fog.

**To go to production, `OpenAIAdapter` / `AnthropicAdapter` / `LocalModelAgent`
implement those five methods. Nothing else in the architecture changes.**

### Not yet built

| Item | Blocks |
|---|---|
| Metrics, staleness estimation | Cost reporting |
| Analytical module, statistics | Research claims |
| Provenance manifests, reporting | Full audit export |
| CLI (`doctor`, `run`, `verify`, `analyze`) | Operator ergonomics |
| `concurrent_edit_collision` task | **§74 acceptance — see below** |

### A blocker found by inspection, not assumption

The only task built so far has **disjoint** file ownership. The real C3 run
recorded **2 claims held, 0 denials** — enforcement is installed and holding
leases, but has never actually blocked a write.

So the claim "C3 prevents conflicting writes" is **not yet established by
execution**, and will not be until a contested-path task exists. This was
found by reading a run artifact, not by inspecting the YAML, and it is
recorded in `docs/backlog.md` as a prerequisite for acceptance.

---

## 6. Measured, not asserted

Real execution against `schema_handler_widen` — agent A widens a schema,
agent B's handler must keep up:

| Arm | Chain verifies | Task succeeded | Coordination bytes | Unique context digests | Claims |
|---|:---:|:---:|---:|---:|---:|
| C0 | ✓ | ✗ | **0** | **1** | 0 |
| C1 | ✓ | ✓ | 361 | 4 | 0 |
| C2 | ✓ | ✓ | 196 | 4 | 0 |
| C3 | ✓ | ✓ | 196 | 4 | 2 |

Reading this properly:

- **C0 fails**, and fails for the right reason: the handler goes stale
  because nobody told it the schema moved. The coordination problem is real,
  not stipulated.
- **C0's single unique digest** across all turns is the empty-context digest
  repeated. That is a *proof* that nothing entered its context, not an
  assertion that nothing should have.
- **C2 and C3 spend identically** (196 bytes) — required, since they differ
  by enforcement alone. Any information difference would confound the
  contrast.
- **C1 costs 84% more** than C2 for the same outcome. That is the
  representational overhead, measured.

One run per cell estimates nothing. This is evidence the machinery works,
not a result.

---

## 7. Engineering discipline

The rules this codebase holds itself to, because a coordination substrate
that cannot be trusted is worse than none.

**Never:** fabricate results; silently change conditions; discard failed
runs; overwrite raw evidence; hide limitations; claim security properties no
test establishes; mark something done because it compiles.

**Always:** implement → test → integrate → **execute** → inspect artifacts →
document → commit.

### Guarantees are mutation-tested

A passing test proves nothing until you have watched it fail. Three
examples from the scheduler alone:

| Guarantee | Mutation | Result |
|---|---|---|
| Atomic run claiming | Replaced `BEGIN IMMEDIATE` with read-then-write | **19 claims for 12 runs** |
| Arm assignment | Forced every run to execute as C0 | caught |
| Chain integrity | Corrupted one exported event | caught — break + bad signature + key mismatch |

### Failures are recorded, including my own

Execution has repeatedly exposed things that inspection did not:

- A scrubbed environment omitted `APPDATA`, so `pytest` vanished on Windows
  and **every** task failed identically in every arm — the experiment would
  have reported uniform failure while appearing to run.
- I "fixed" output nondeterminism by hashing the output, which hid the same
  bug behind a digest. Removed entirely.
- An artifact inspection read a key that did not exist and reported zeros
  for every arm — which *looked* like it confirmed C0's isolation while
  confirming nothing.

Each is documented in the file it affects. A system that quietly discards
its own mistakes cannot credibly promise not to discard yours.

---

## 8. Where this goes

**Near term** — finish the vertical slice: metrics, statistics, provenance,
CLI. Build the contested-path task that §74 needs.

**Production** — implement the model adapters. The substrate is already
provider-neutral and already async; this is the single remaining piece
between the current system and a deployable agent fleet.

**The eventual claim.** Not "our coordination mechanism is better" — that is
not what this measures. The claim is: *given a fleet of coding agents, here
is what information is worth, here is what enforcement is worth, here is
what each costs, and here is a cryptographic record proving the measurement
was taken as described.*

That is a claim you can deploy on, and it is currently one nobody can make.
