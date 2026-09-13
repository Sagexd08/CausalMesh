# CausalMesh

**A research-grade experimental platform for separating _information_ from _enforcement_ in distributed LLM coding agents.**

---

## The research question

> How much of the coordination benefit in distributed LLM coding agents comes from **information**, and how much comes from **enforcement**?

When multiple coding agents work on a shared codebase, they interfere: they make stale reads, duplicate each other's work, and overwrite each other's changes. Systems that fix this usually do two things at once — they *tell* agents what peers are doing, and they *prevent* agents from conflicting. Because these arrive together, their individual contributions are unknown.

CausalMesh separates them experimentally. The contribution is **measurement**, not the invention of a new coordination mechanism.

## Experimental design

Four arms, manipulating exactly two factors:

| Arm | Information | Enforcement | Description |
|:---:|---|---|---|
| **C0** | none | none | Fully isolated agents, no peer visibility |
| **C1** | unbounded transcript | none | Agents see a full conversational transcript |
| **C2** | bounded structured metadata | none | Agents see typed events describing what changed |
| **C3** | bounded structured metadata | write claims | Metadata **plus** enforced exclusive write claims |

The contrasts that answer the question:

```
C0 → C2    information benefit
C1 → C2    information representation / coordination cost
C2 → C3    enforcement benefit
C1 → C3    complete coordinated system
```

Everything other than information and enforcement is held constant: task, model, decoding parameters, agent roles, repository fixture, tool semantics, success criteria, randomization protocol. Anything that cannot be held constant is recorded and treated as a potential confound.

## Architecture

```
                         ┌───────────────────────────┐
                         │       Experiment DB       │
                         └─────────────┬─────────────┘
                                       │
                         ┌─────────────▼─────────────┐
                         │    Experiment Scheduler   │
                         └─────────────┬─────────────┘
              ┌────────────────────────┼────────────────────────┐
        ┌─────▼─────┐            ┌─────▼─────┐            ┌─────▼─────┐
        │  Agent A  │            │  Agent B  │            │  Agent N  │
        └─────┬─────┘            └─────┬─────┘            └─────┬─────┘
              └───────────────┬────────┴───────────────┬────────┘
                              │  Lifecycle Hooks
                     ┌────────▼────────┐
                     │  Coordination   │
                     │    Boundary     │
                     └────────┬────────┘
                        ┌─────▼─────┐
                        │   Relay   │
                        └─────┬─────┘
              ┌───────────────┼────────────────┐
        ┌─────▼─────┐   ┌─────▼─────┐    ┌─────▼─────┐
        │ Event Log │   │  Claims   │    │  Fan-out  │
        └─────┬─────┘   └─────┬─────┘    └─────┬─────┘
              └───────────────┼────────────────┘
                       ┌──────▼──────┐
                       │   Observer  │
                       └──────┬──────┘
                      ┌───────▼────────┐
                      │ Offline Verify │
                      └───────┬────────┘
                     ┌────────▼─────────┐
                     │ Research Dataset │
                     └────────┬─────────┘
                     ┌────────▼─────────┐
                     │ Analysis Engine  │
                     └────────┬─────────┘
               ┌──────────────┼──────────────┐
             plots          tables          report
```

Dependencies run one way only. Analysis never mutates runtime state, the verifier never depends on the relay being online, and the observer is strictly read-only.

## Measurement integrity

Every coordination event is appended to a cryptographic chain:

```
h_i = SHA256( h_(i-1) || canonical(event_i) )
```

Each event is signed with a per-actor Ed25519 key, so attribution is verifiable rather than asserted. A **standalone offline verifier** validates the chain from nothing but the log, the public keys, and optional anchors — the relay can be completely offline.

The adversarial battery tests what the chain actually detects:

| Attack | Expected result |
|---|---|
| Event mutation | detected |
| Event insertion | detected |
| Event deletion | detected |
| Event reordering | detected |
| Signature substitution | detected |
| Wrong-actor attribution | detected |
| Duplicate replay | detected |
| Suffix truncation | **undetected without an anchor**, detected with one |

That last row is a real limitation, documented rather than hidden.

## Status

**Substrate complete and exercised. 797 tests passing.**

The build follows a vertical slice first: a single scenario driven end-to-end
through every subsystem, executed under all four arms, before breadth is
added. No subsystem is considered complete until it participates in a real
executable path.

| Subsystem | State |
|---|---|
| Event protocol, canonicalization | ✅ property-tested |
| Ed25519 identity, hash chain | ✅ |
| Offline verifier + adversarial battery | ✅ 8 attack classes |
| Claim registry, leases | ✅ concurrency-tested across threads |
| Relay: sequence, sign, chain, fan-out | ✅ |
| Isolation, 11 tools, lifecycle hooks | ✅ leakage-tested |
| Channels, relevance, information window | ✅ |
| Script-driven agent | ✅ |
| Task system + empirical §37 gate | ✅ 2 tasks |
| Scheduler, state machine, run index | ✅ resume-tested |
| Model adapters (OpenAI, Anthropic, local) | ✅ tested over real HTTP |
| Metrics, statistics, provenance, CLI | ⬜ not built |

Not yet done, and stated plainly: **no hosted model has been run** (no key was
available, and spending money is the operator's decision), and the analysis
and reporting layers do not exist. See [`docs/backlog.md`](docs/backlog.md),
which records every gap as a tracked item with its reason.

## Measured results

A real pilot collection — 2 tasks × 4 arms × 3 repetitions = **24 runs**,
executed on this machine, 150 s wall clock. Nothing below is illustrative.

| Arm | Success | Mean coordination bytes | Denials | Divergences | Chains verified |
|:---:|:---:|---:|---:|---:|:---:|
| C0 | 0/6 | **0** | 0 | 6 | 6/6 |
| C1 | 6/6 | 361 | 0 | 0 | 6/6 |
| C2 | 6/6 | 196 | 0 | 0 | 6/6 |
| C3 | 3/6 | 196 | 3 | 0 | 6/6 |

Reading it:

- **C0 fails every run.** Isolated agents make exactly the stale-read and
  clobber errors the tasks induce. Zero coordination bytes, and a single
  unique context digest across all turns — proof that nothing entered, not an
  assertion that nothing should have.
- **Information alone recovers everything** on both tasks. C1 and C2 are 6/6.
- **C1 costs 84% more than C2** for identical outcomes. That is the
  representational overhead, measured.
- **C2 and C3 spend identically** (196 bytes), as they must: they differ by
  enforcement alone, and any information difference would confound the
  contrast.
- **C3 splits 3/3 and 0/3.** Where ownership is disjoint it matches C2. Where
  the path is genuinely contested, enforcement *prevents the clobber and
  blocks legitimate work* — the file needs two writers. That is §74's
  trade-off measured rather than assumed to be an improvement.
- **All 24 chains verify offline**, rebuilt from each run's derived seed.

One pilot estimates a direction, not an effect size. The confirmatory design
(1920 runs) is built and **gated**: it commits to a preregistered analysis
this project has not written.

## 📋 Implementation plan

**→ [`docs/PLAN.md`](docs/PLAN.md) — the full implementation plan.**

It covers the architecture, the honest security model, the 17-step build sequence, the verification procedure, and the explicit non-goals of the current slice.

## Usage

The Python API is what exists today; the CLI is Step 15 and not yet built.

```python
from causalmesh.experiments import plan_experiment, profile
from causalmesh.scheduler import ExperimentRunner, RunEnvironment
from causalmesh.tasks import TaskDefinition

task = TaskDefinition.from_yaml("tasks/schema_handler_widen.yaml")
plan = plan_experiment(
    experiment_id="my_run", profile=profile("smoke"),
    task_ids=[task.task_id], master_seed=b"a-recorded-seed",
)
env = RunEnvironment.under(".", experiment_id="my_run")
with ExperimentRunner(plan=plan, tasks={task.task_id: task},
                      environment=env, master_seed=b"a-recorded-seed") as r:
    r.prepare()
    report = await r.run()
```

Run the suite with `pytest`. The slow integration tests execute real
subprocesses; `pytest -m "not slow"` skips them.

### Planned CLI (Step 15)

```bash
causalmesh doctor                          # environment health check
causalmesh task validate                   # validate the task suite
causalmesh experiment plan --profile smoke # produce a run schedule
causalmesh experiment run  --profile smoke # execute
causalmesh verify --all                    # offline chain verification
causalmesh analyze --latest                # statistical analysis
causalmesh report  --latest                # figures, tables, report
```

## Design commitments

- **No fabricated results.** Ever. Not results, not benchmarks, not model outputs.
- **Raw data is immutable.** Once written, `data/raw/` is never modified by analysis.
- **Failed runs are evidence.** They are recorded with full context, never silently discarded.
- **No overclaiming.** Security properties are stated only where a passing test establishes them; the threat model documents what is *not* protected.
- **Full traceability.** Every reported number traces from the claim, through the analysis, through processed data, through the run, through the signed event chain, back to the exact task, configuration, model and commit that produced it.

## Repository layout

```
configs/      experiment, agent, model, relay, claim and task configuration
src/          the causalmesh package
tasks/        declarative task definitions
fixtures/     repository fixtures used by tasks
data/         raw (immutable), processed, manifests, exports
artifacts/    chains, metrics, plots, tables, reports, certificates
tests/        unit, integration, property, adversarial, failure, reproducibility
docs/         architecture, protocol, events, claims, security, analysis
frontend/     landing page (React + Vite + Tailwind)
```

## Documentation

| Document | What it covers |
|---|---|
| [`docs/IDEA.md`](docs/IDEA.md) | What this is and why, for a deployment reader |
| [`docs/PLAN.md`](docs/PLAN.md) | The full build sequence |
| [`docs/security.md`](docs/security.md) | The three-layer isolation model and its limits |
| [`docs/adapters.md`](docs/adapters.md) | Model adapters, and what has not been executed |
| [`docs/scheduler.md`](docs/scheduler.md) | The run loop, state machine and randomization |
| [`docs/claims.md`](docs/claims.md) | Write leases and enforcement |
| [`docs/tasks.md`](docs/tasks.md) | Task definitions and the §37 sensitivity gate |
| [`docs/backlog.md`](docs/backlog.md) | Every known gap, with its reason |

## Requirements

Python 3.11+ and Git. The analysis stack uses numpy, scipy, pandas, statsmodels and matplotlib; the runtime core deliberately stays lighter, leaning on the standard library and `cryptography` for Ed25519. No Kafka, Redis, Kubernetes, Prometheus or Grafana.

## License

MIT — see [LICENSE](LICENSE).
