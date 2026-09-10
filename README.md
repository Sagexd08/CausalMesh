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

🚧 **Under active construction.** Currently at Step 0 (repository bootstrap) of the plan below.

The build follows a vertical slice first: a single scenario driven end-to-end through every subsystem, executed under all four arms, before breadth is added. No subsystem is considered complete until it participates in a real executable path.

## 📋 Implementation plan

**→ [`docs/PLAN.md`](docs/PLAN.md) — the full implementation plan.**

It covers the architecture, the honest security model, the 17-step build sequence, the verification procedure, and the explicit non-goals of the current slice.

## Planned usage

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
```

## Requirements

Python 3.11+ and Git. The analysis stack uses numpy, scipy, pandas, statsmodels and matplotlib; the runtime core deliberately stays lighter, leaning on the standard library and `cryptography` for Ed25519. No Kafka, Redis, Kubernetes, Prometheus or Grafana.

## License

MIT — see [LICENSE](LICENSE).
