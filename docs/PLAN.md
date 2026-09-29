# CausalMesh — Vertical Slice Implementation Plan

## Context

**The research question.** CausalMesh exists to measure how much of the coordination benefit in distributed LLM coding agents comes from *information* (agents knowing what peers did) versus *enforcement* (agents being prevented from making conflicting writes). These two factors are normally entangled: a system that shares information usually also coordinates locks. The contribution of this project is the experimental *separation* of the two, not the invention of a new coordination mechanism.

**Why this plan exists.** The full specification runs to 98 sections describing roughly 20 subsystems and a 1920-run confirmatory experiment. Building all of it before executing anything would produce exactly the failure the specification forbids in §92 — disconnected modules that compile but are never exercised. §71 prescribes a vertical slice first. This plan builds that slice end-to-end so every subsystem is proven on a real executable path, then expands breadth on a spine already known to work.

## Decisions taken

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Vertical slice first (§71) | Reaches the §72 acceptance test with every component exercised |
| Adapters | MockAgent only | No API keys, no cost, no model nondeterminism; infrastructure validated deterministically |
| Run scale | Smoke + pilot executed; confirmatory gated | Machinery and §77 gates built, gate stays closed. No fabricated results |
| C0 isolation | OS process separation + path enforcement + context audit | See the honesty note below |
| Signatures | Ed25519 per-actor keys | Uses already-installed `cryptography`; makes §58 attribution tests meaningful |

## Verified environment

No new dependencies are required. Confirmed on this machine:

- Python 3.13.5, SQLite 3.49.1
- Docker 29.7.2 (daemon live), WSL2
- 12 logical cores / 23.3 GB RAM
- multiprocessing is `spawn`-only; Windows Job Objects reachable via `ctypes` and `pywin32`
- Installed: `cryptography` 50.0.1 (Ed25519 available), numpy, scipy, pandas, statsmodels, matplotlib, PyYAML, pytest (+asyncio/xdist/timeout), hypothesis, typer, rich

---

## Honesty note on the C0 sandbox (§14, §87)

Empirical check on this machine: `spawn`-only multiprocessing gives each agent a fresh interpreter with no inherited memory, and per-process `cwd` works as expected. However, **Windows has no `chroot` and no mount namespaces, so per-process `cwd` is process separation, not a filesystem jail.** A child process can still reach any path its user token permits.

The implementation therefore uses three layers, each with a separately stated guarantee. `docs/isolation.md` states precisely this rather than claiming a jail that does not exist:

| Layer | Mechanism | What it actually guarantees |
|---|---|---|
| L1 Process | `spawn` subprocess per agent, own cwd, scrubbed environment | No shared memory, no inherited handles, no ambient coordination state |
| L2 Path | Every tool call resolves through `realpath` and must fall inside the agent's workspace root; symlinks, junctions and `..` traversal rejected | Agents cannot reach peer workspaces *through the sanctioned tool API* — enforced and unit-tested |
| L3 Context | Single typed injection point; `NullChannel` raises under C0; per-turn SHA-256 digest of injected bytes plus a coordination-byte counter | Provable claim that C0 received zero coordination bytes |

**L3 is what actually answers §96's "can we prove C0 received no coordination information?"** L1 and L2 close side channels; L3 produces the evidence. A post-run assertion fails the run if any C0 counter is non-zero. Docker is wired into `docker-compose.yml` as the optional stronger jail for Linux and CI, documented as optional rather than required for the slice.

---

## Architecture

Strict one-way dependency direction, enforced by an import-boundary test (§5):

```
configs ─→ runtime (agents, hooks, tools, isolation)
             ↓ emits typed events
           relay (ingest, sequence, sign, chain, claims, fan-out)
             ↓ writes
           data/raw/**  ← IMMUTABLE after run finalization (§31)
             ↓ read-only
           verifier (offline, no relay dependency) ─→ certificates
             ↓
           metrics ─→ data/processed ─→ analysis ─→ artifacts/{plots,tables,reports}
```

Invariants the tests enforce: analysis never imports runtime; the verifier never imports the relay; the observer is read-only; the scheduler never touches agent internals.

## Package layout

Repository root is the project root, with the package at `src/causalmesh/`. Every module has a named consumer (§92 — no dead code):

| Module | Purpose | Consumer |
|---|---|---|
| `events/` | Schema, canonicalization, hashing | relay, verifier, property tests |
| `crypto/` | Ed25519 keypairs, signing, verification | relay, verifier, adversarial suite |
| `relay/` | Append, sequencing, chaining, fan-out | runtime, CLI |
| `claims/` | SQLite transactional lease registry | relay, C3 gate, integration tests |
| `channels/` | `NullChannel` (C0), `TranscriptChannel` (C1), `MetadataChannel` (C2/C3) | hooks |
| `relevance/` | Deterministic scorer with stored reasons | metadata channel |
| `hooks/` | Pre/post tool lifecycle boundary | tools |
| `tools/` | The 11 controlled tools (§12) with L2 path validation | agents |
| `isolation/` | Workspace construction, process spawn, path jail | scheduler |
| `agents/`, `adapters/` | `CodingAgent` interface and scripted MockAgent | scheduler |
| `jev/` | Typed decision engine client (Choice/Score/Noul) for TypeSafe AI's Jev | its own test suite only — no runtime caller yet; see `docs/backlog.md` |
| `experiments/`, `scheduler/`, `tasks/` | Arms, randomization, run loop, task validation | CLI |
| `storage/` | SQLite operational index | scheduler, CLI |
| `metrics/`, `analysis/`, `reporting/` | Accounting, contrasts, figures, tables, report | CLI |
| `verifier/`, `adversarial/` | Offline verification and attack battery | CLI, tests |
| `provenance/`, `cli/` | Manifests, hashes, typer CLI | CLI |

---

## Build sequence

Each step follows §91: implement → unit test → integration test → **execute for real** → inspect artifacts → document → commit. A step is not done until its artifacts have been opened and read.

### Step 0 — Repository bootstrap
Directory scaffold, `git init`, `main` branch, remote, `.gitignore` (keeps `data/raw` immutable while tracking manifests), `pyproject.toml`, `Makefile`, `.env.example`, LICENSE, README. Editable install, then confirm `causalmesh --help` runs.

### Step 1 — Event protocol and canonicalization (§25, §29)
Versioned event dataclasses. Canonical serializer with sorted keys, explicit UTF-8/NFC normalization, RFC 3339 UTC timestamps, integer-only sequences, and rejection of floats and NaN. Property tests via hypothesis cover round-trip determinism, key-order independence, unicode normalization, and nested-object stability. This step is load-bearing: ambiguous serialization silently breaks every downstream hash.

### Step 2 — Crypto and hash chain (§24)
Ed25519 per-actor keypairs derived deterministically from `master_seed + actor_id` for reproducibility. Chain rule `h_i = SHA256(h_{i-1} || canonical(event_i))` with signed heads and explicit genesis handling.

### Step 3 — Offline verifier and adversarial battery (§26, §27, §58)
Standalone verifier taking only `(log, public keys, optional anchors)`; an import test asserts it never pulls in the relay. Attack battery: mutation, insertion, deletion, reordering, signature substitution, wrong-actor attribution, duplicate replay and anchor mismatch must all be **detected**. Suffix truncation is **undetected without an anchor and detected with one** — a documented limitation per §87, not a defect.

### Step 4 — Claims and leases (§19–21)
SQLite with `BEGIN IMMEDIATE` transactions for genuine atomicity. Operations: `acquire`, `renew`, `release`, `check`, `expire`. Invariant: at most one valid writer claim per path at any instant. A property test hammers concurrent acquisition across processes. Denied writes must leave the target byte-identical, asserted by hashing before and after.

### Step 5 — Relay (§55)
Ingestion, monotonic sequence assignment, signing, chaining, claim gate, fan-out, observer stream and export. The relay must not judge task correctness or rewrite events.

### Step 6 — Isolation, tools and hooks (§11–13)
The three-layer sandbox described above, with all 11 tools behind the lifecycle boundary. A dedicated leakage test attempts peer-workspace access by relative path, absolute path, symlink, junction and `..` traversal; every attempt must be denied and logged.

### Step 7 — Channels, relevance and information window (§15–18)
`NullChannel` raises on any injection attempt (C0). The transcript channel measures token growth with no silent truncation. The metadata channel uses a configurable window (default `w = 8`) and records `events_available / selected / injected / dropped` plus per-event selection reasons. Every injection records a context digest and coordination-byte delta feeding the §14 proof.

### Step 8 — MockAgent (§9)
Deterministic and YAML-scripted: read, write, modify, emit intents, respond to coordination events, plus deliberate conflicts, stale reads, delayed deliberation, crashes, stalls and retries. This is the laboratory, not a test double.

### Step 9 — Task system and first task (§35–38)
Declarative tasks with fixture, roles, dependency graph, integration tests and divergence checks. The §37 quality gate requires a deterministic validation run to *empirically demonstrate* that the coordination dependency exists — a task is not coordination-sensitive merely because its YAML says so. Success requires integration tests passing **and** induced divergence being absent; no subjective labels.

### Step 10 — Run loop, arms and scheduler (§39–42, §79–81) — **done**
The §79 execution loop with the §63 state machine, reproducible randomization from `master_seed + task_id`, resume support and idempotency. Failed runs still produce full evidence (§81): a failed run is evidence, not garbage.

Executed: the smoke profile against `schema_handler_widen`, 4 runs, order **C3, C1, C2, C0** (randomized, not blocked). All four chains verify offline from their persisted artifacts. C0 recorded zero coordination bytes and a single unique turn digest across all turns; C2 and C3 spent identically. See `docs/scheduler.md`.

Three guarantees were mutation-tested rather than assumed: replacing the atomic claim transaction produced 19 claims for 12 runs; forcing every run to execute as C0 while the index recorded the planned arm was caught; corrupting one exported event was caught by offline verification.

### Step 11 — Metrics and staleness (§23, §44, §45) — **partially done**
Per-turn coordination-token accounting that separates task-reasoning cost from coordination cost. Staleness instrumentation estimating λ̂, δ̂ and Δ̂, keeping **observed** values strictly distinct from **predicted** curves.

**Built:** `metrics/` aggregates the cost the channel recorded — bytes, tokens, events available versus injected, per run, per arm and per task — and applies the four planned contrasts from `experiments/arms.py`. It measures nothing itself: recomputing a cost from event payloads would produce a second figure for the same quantity, and the two would diverge the moment the channel's accounting changed.

`causalmesh analyze` reports it, per task by default. Pooling is opt-in behind `--pooled` because on this design the pooled enforcement contrast is actively misleading: enforcement costs nothing on `schema_handler_widen` (disjoint ownership, nothing to block) and every success on `concurrent_edit_collision` (contested path), and the mean of 0.00 and −1.00 describes neither task.

An absent outcome is counted as `unknown`, never as a failure — a crashed run recorded as a failure would inflate every failure rate by however many runs crashed before evaluating.

**Not built:** the staleness estimators. λ̂, δ̂ and Δ̂ are named here and defined nowhere in this repository; they come from §23 and §45, which are not checked in. The per-turn observations would support *an* estimator, but one derived from its own inputs would carry the specified symbol while possibly measuring something else. Recorded in `docs/backlog.md` rather than guessed.

### Step 12 — Analytical module (§46, §47) — **not built**
Pure mathematics with zero storage dependency, unit-tested against hand-computed values: `C_tr`, `C_md`, `ρ(T)`, `T*`, `P_stale`, `P_floor`.

### Step 13 — Statistics (§48–50) — **not built**
The preregistered mixed-effects logistic model with task random intercepts, the four primary contrasts, Holm–Bonferroni correction, 95% confidence intervals, TOST at ±10 percentage points (a non-significant difference is explicitly *not* an equivalence result), and configurable power analysis that states its assumptions.

### Step 14 — Provenance, manifests and reporting (§30–33, §60, §66–69) — **partially done**
Manifests carrying SHA-256 hashes of every artifact, environment capture and a configuration freeze hash. The report generator ensures every number carries a traceable source reference and every figure and table is labeled ANALYTICAL, PILOT, CONFIRMATORY, EXPLORATORY or DERIVED.

**Built:** `provenance/` captures the environment (§30, §32) and writes manifests (§31, §33). `causalmesh manifest write` records a SHA-256 over every artifact plus a configuration freeze hash; `causalmesh audit` checks the record against what is on disk and **re-verifies every chain**, because a manifest proves the bytes are unchanged and says nothing about whether they were ever valid.

Manifests are tracked in git while `data/raw/` is not, which is what keeps a published figure traceable to its run after the raw directory is gone.

Three `RunConfig` fields — `git_commit`, `machine_id`, `operator_id` — existed and defaulted to `"unknown"` because nothing populated them, so every run produced before this was unattributable. `experiment run` now captures them. They are recorded in the artifact **envelope**, never in the signed chain: the chain is bit-reproducible, and a hostname or commit hash inside it would break that. Verified by executing the same collection twice under one seed and confirming all four head hashes match.

A manifest recorded from a dirty working tree reports itself as not attributable to a commit, rather than implying the tree matched the hash it names.

**Not built:** the report generator, and the §68 figure labelling it would apply. `causalmesh analyze` labels its own tables PILOT and DERIVED in the meantime.

### Step 15 — CLI, doctor, audit and docs (§61, §62, §83, §94) — **partially done**
All §62 commands with `--help` and meaningful exit codes. `doctor` reports PASS/WARN/FAIL with actionable diagnostics. `audit` detects untested modules, missing provenance, unverified runs, dirty raw data and configuration mismatches. All ten `docs/*.md` files describe **actual** behavior.

**Partially done.** Built and exercised: `doctor`, `task list`, `task validate`, `experiment plan`, `experiment run`, `experiment status`, `verify` (including `--run` for the §82 clean-room case). Every command takes `--json`; exit codes are 0 success, 1 negative result, 2 bad invocation, 3 could not run. A failed *run* exits 0, because §81 makes a failed run evidence.

Later built and exercised (this paragraph previously said otherwise): `analyze` (descriptive, on `metrics/`), `manifest write` and `audit` (on `provenance/`), `watch`, `connectors list`, `policy`, `serve`, `quickstart` and `agreement`. Not built: `report`. It waits on `reporting/`, which is empty. `causalmesh doctor` names the unbuilt subsystems rather than leaving them to be discovered by use.

`analysis/` is no longer empty: `agreement.py` (multi-rater kappa coding, §53 — see `docs/backlog.md`) is built and exposed as `causalmesh agreement`. It computes over an operator-supplied judgement file only; no run in this repository has been coded by a real rater.

Two defects surfaced by running the CLI against real artifacts, both the same shape as the enforcement-measurement defect in `docs/backlog.md`: a read of a field that does not exist, reporting a confident zero. The key ring was built from `event.actor_id` when the actor is at `event.identity.agent_id`, so every chain failed verification; and `status` counted `result.success` when success is `result.outcome.succeeded`, so every arm showed zero passes. The second now counts an absent outcome as `unknown` rather than as a failure.

### Step 16 — Acceptance execution
Execute the §72 sequence for real, then §73 (four arms independently observable), §74 (collision, where C3 prevents the conflicting write and the trade-off is *measured* rather than assumed to be an improvement), §75 (fault injection) and §76 (pilot with parameter estimates stored separately from reference assumptions).

---

## Verification

**Automated.** `pytest` across unit, integration, property, adversarial, failure and reproducibility suites; import-boundary tests; a reproducibility test asserting that identical seed, config and task yield structurally equivalent chains.

**End-to-end, executed and inspected:**

```bash
causalmesh doctor
causalmesh task validate
causalmesh experiment plan --profile smoke
causalmesh experiment run  --profile smoke
causalmesh verify --all
causalmesh analyze --latest
causalmesh report  --latest
```

**Manual inspection**, reading actual artifacts rather than asserting success:

1. Open the raw chain; confirm hashes link and signatures verify offline with the relay stopped.
2. Confirm C0 runs record **zero** coordination bytes and an empty injection digest set.
3. Confirm C1 contains a transcript, C2 bounded metadata (at most `w` events, with reasons) and C3 metadata **plus** denial records.
4. Confirm a denied write left the target file byte-identical.
5. Confirm every number in the generated report resolves back to a raw run.

**Clean-room check (§82).** Export artifacts, then verify and analyze them from a separate directory with no relay and no access to the source tree.

---

## Explicit non-goals for this slice

Each is recorded as a tracked item in `docs/backlog.md` rather than left as a silent gap:

- Real LLM adapters (OpenAI, Anthropic, local)
- CooperBench import (§54) — loader built and proven on one synthetic
  worked example with a real §37 run; the real 30-task dataset is not
  imported (see `docs/backlog.md`)
- Multi-rater kappa coding (§53) — coding scheme and kappa computation built; no run coded by a real rater
- Scaling beyond 4 agents (§86)
- The 1920-run confirmatory execution — machinery and gates built, gate closed

---

## Standing commitments

No fabricated results. No silently discarded runs. No raw-data mutation. No security claim beyond what a passing test establishes. No feature marked complete merely because it compiles. Where an implementation falls short, the documentation says so plainly.
