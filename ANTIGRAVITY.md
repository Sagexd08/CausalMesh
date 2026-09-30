# CausalMesh — Antigravity Engineering Instructions

## 1. Project Mission

CausalMesh is an AI-agent infrastructure SDK and Tool Gateway that provides a controlled execution boundary for agents.

Canonical runtime flow:

`Agent → CausalMesh SDK → Tool Gateway → Lifecycle Boundary → Policy / Contract Gate → Tool Handler → Evidence`

The gateway and policy boundary are mandatory. Never bypass them for convenience, tests, adapters, demos, or internal tooling.

This repository is developed as a real product. Favor reliability, backward compatibility, security, testability, rollout safety, observability, and clear user impact.

## 2. Antigravity Multi-Agent Workflow

Antigravity may use multiple specialized sub-agents.

### Worktree isolation

Every implementation sub-agent MUST work in its own isolated Git worktree and branch.

Recommended pattern:

`dev`
→ `agy/<area>`
→ dedicated worktree for that agent

Agents must not share an active working tree.

### Integration

The final integration target is **dev**.

Rules:

- Do not merge work into `main`.
- Do not rewrite `main`.
- Do not force-push unless explicitly authorized.
- Do not merge unreviewed or failing work.
- Each sub-agent must commit its changes on its own branch.
- Each sub-agent must report:
  - branch name
  - commit SHA
  - files changed
  - tests/checks executed
  - exact failures or limitations
- The lead agent reviews conflicts, tests, security implications, and compatibility before merging into `dev`.

### Integration order

Prefer dependency-aware integration:

1. core contracts / schemas
2. SDK and gateway behavior
3. evidence / policy infrastructure
4. server and adapters
5. CLI / TUI / developer experience
6. frontend / website
7. packaging / release
8. docs

When changes overlap heavily, integrate the lowest-level dependency first and rebase or resolve higher-level branches afterward.

## 3. Engineering Principles

### Correctness before completeness

Never fabricate:

- benchmark results
- human-rater judgments
- research findings
- external-provider results
- production validation
- customer usage
- security guarantees

When an item requires unavailable external resources, classify it honestly as external, blocked, human-required, or unverified.

### Fail closed

Security, policy, identity, resource, authorization, budget, and evidence failures must fail closed.

A denied operation must not execute the handler.

Unknown agents, undeclared resources, invalid resource kinds, malformed inputs, invalid identities, and policy violations must not silently fall through.

### Backward compatibility

Avoid unnecessary breaking changes.

Before changing a public API:

- inspect current callers and tests
- preserve compatibility where practical
- document intentional breaking changes
- add regression tests

### Observability

Important execution paths should remain inspectable through structured evidence, logs, request IDs, and deterministic testable behavior.

Never solve observability problems by bypassing policy or lifecycle boundaries.

## 4. Backlog Execution Rules

For every backlog item, classify it before implementation:

- **DONE** — already implemented and verified
- **TESTED** — implementation exists and verification is the remaining work
- **PARTIAL** — some implementation exists
- **IMPLEMENT** — locally buildable and actionable
- **EXTERNAL** — requires a third-party service, account, API key, dataset, or environment
- **HUMAN** — requires human judgment, annotation, approval, or manual research
- **RESEARCH** — requires new empirical study or investigation
- **BLOCKED** — cannot safely proceed with available information

Never mark an item complete merely because code was written.

## 5. Security Invariants

The following invariants are mandatory:

1. Tool execution goes through the Tool Gateway.
2. Policy / contract checks happen before the handler runs.
3. Denied mutating operations do not invoke handlers.
4. Unknown agents fail before handler execution.
5. Missing or undeclared resources fail closed.
6. Resource kinds must be declared and validated.
7. Identity binding must be explicit and consistent.
8. Evidence records must reflect the real operation and event type.
9. Unenforced policy arms must not masquerade as enforced decisions.
10. Resource canonicalization must prevent path/resource confusion.
11. Invalid or unsafe inputs must fail closed.
12. Secrets and sensitive identifiers must never be committed to the repository.
13. Redirects and upstream behavior must not silently weaken security guarantees.
14. Budget enforcement must use the authoritative ledger where required.
15. No adapter or convenience API may bypass the gateway.

Never weaken a security invariant just to make a test, demo, benchmark, or adapter pass.

## 6. SDK Rules

Use the public SDK APIs.

Preferred:

- `CausalMesh.from_config(...)`
- `mesh.register_tool(...)`
- `mesh.execute(...)`

Do not depend on private implementation details such as:

- `_mesh._gateway`
- private fields
- private test helpers
- undocumented module internals

When a feature genuinely requires new public functionality, add a stable public API rather than reaching around the abstraction.

## 7. Gateway / Policy Rules

The Tool Gateway is the execution boundary.

Every tool call must have a clear path through:

- identity
- resource declaration
- policy / contract decision
- handler execution
- evidence

Mutating defaults, evidence event types, budgets, rate limits, and denial semantics must remain consistent with the current repository contract and tests.

## 8. Server Rules

The server must preserve the gateway invariants over HTTP.

Pay attention to:

- authentication
- identity binding
- request size limits
- rate limiting
- request IDs
- timeout behavior
- async event-loop safety
- redirect handling
- readiness / health behavior
- safe error responses
- non-root container execution
- production-safe configuration defaults

Never expose a server path that executes a tool without policy enforcement.

## 9. Evidence Rules

Evidence is a first-class product capability.

Evidence-related work should preserve:

- deterministic event semantics
- stable identifiers
- causal ordering
- reproducible signed chains
- export / verification integrity
- checkpoint semantics
- claim provenance

Never invent evidence to make a benchmark or research result appear complete.

## 10. Adapters

Framework integrations must adapt into the CausalMesh public boundary.

Supported or planned integrations may include:

- Anthropic
- LangGraph
- CrewAI

Adapters may use mocks for local testing when real external credentials are unavailable.

Do not claim a real external integration is validated when only mocks or local simulations were run.

## 11. CLI / TUI / Developer Experience

Developer-facing interfaces should make the safe path the easy path.

Examples:

- local quality gate
- clear diagnostics
- useful request IDs
- readable policy decisions
- evidence inspection
- reproducible verification commands

Do not add decorative UI while core correctness, security, packaging, or end-to-end execution is broken.

## 12. Testing

Every implementation must add or update tests appropriate to the risk.

At minimum, verify:

- happy path
- denial path
- malformed input
- unknown identity
- undeclared resource
- handler-not-called-on-denial
- async behavior where applicable
- regression behavior
- public API compatibility

Run the repository's local quality gate:

`python scripts/check.py`

When a check cannot run because of environment limitations, report it explicitly. Do not replace missing verification with assumptions.

No GitHub Actions or paid CI should be introduced unless explicitly requested.

## 13. Packaging and Release

The package should be installable through the supported Python packaging flow.

Before release:

1. validate package metadata
2. build source/wheel artifacts
3. test installation in a clean environment
4. test the documented quickstart
5. verify CLI entry points
6. verify runtime imports
7. review dependency floors
8. confirm no secrets or private identifiers are included

PyPI publication requires the appropriate account/token and must not be faked or implied.

Do not automatically publish to PyPI without explicit authorization.

## 14. Docker / Deployment

Deployment work must be reproducible.

Validate:

- image build
- container startup
- health/readiness behavior
- non-root execution
- environment configuration
- network/security assumptions
- documented run commands

Do not claim hosted production readiness without the required external infrastructure validation.

## 15. Frontend / Website

The frontend should present a coherent end-to-end product path.

Priorities:

1. correct integration with real backend APIs
2. clear auth/configuration
3. useful execution and evidence views
4. understandable policy outcomes
5. reliable build/install
6. visual polish

Do not create a fake end-to-end experience backed only by hard-coded demo data unless it is explicitly labeled as a mock/demo.

## 16. Research / Benchmark Guardrails

Some backlog items require real-world or human validation.

Examples include:

- human-rater coding
- confirmatory experiments
- real benchmark datasets
- real hosted-model runs
- real CooperBench executions
- empirical staleness evaluation

For these, implement the surrounding software infrastructure locally when useful, but clearly separate:

**software readiness** from **empirical completion**.

Never fabricate the missing empirical portion.

## 17. External Dependencies

Items requiring any of the following must be explicitly identified:

- API keys
- paid inference
- hosted services
- third-party accounts
- external datasets
- operator credentials
- payment signers
- manual approval
- human annotation

Build the local interfaces, schemas, mocks, and tests where possible without pretending the external portion is complete.

## 18. Git Hygiene

Keep commits focused and reviewable.

Preferred commit style:

`<type>: <short description>`

Examples:

- `fix(server): enforce request identity binding`
- `feat(evidence): add signed export verification`
- `test(sdk): cover undeclared resource denial`
- `docs(release): document clean-install workflow`

Do not commit:

- credentials
- tokens
- private identifiers
- machine-specific state
- generated junk
- temporary debug artifacts

Do not rewrite history merely to make the current tree look cleaner unless explicitly authorized.

## 19. Sub-Agent Completion Contract

Before an agent declares completion, it must provide:

```
AREA:
BRANCH:
WORKTREE:
STATUS: DONE | PARTIAL | BLOCKED | EXTERNAL | HUMAN
COMMITS:
FILES:
TESTS:
QUALITY GATE:
KNOWN LIMITATIONS:
INTEGRATION NOTES:
```

The lead agent must review this report before merging.

## 20. End-to-End Completion Standard

The product is considered locally end-to-end only when a clean environment can:

1. install the package
2. import the public SDK
3. configure a mesh
4. register a tool
5. submit an execution
6. pass through the gateway
7. enforce policy / contract
8. execute the handler only when allowed
9. produce evidence
10. inspect or verify the resulting evidence
11. exercise the server path where supported
12. run the documented checks successfully

Anything requiring external credentials, human judgment, real benchmark execution, or production infrastructure remains explicitly marked as such.

## 21. Antigravity Operating Rule

Do the work. Do not stop at analysis when the task is locally actionable.

For locally buildable backlog items:

- inspect first
- design the smallest correct change
- implement
- test
- review
- commit
- report
- integrate into `dev`

For blocked or external items:

- prepare the local implementation/interface
- add mocks/tests where appropriate
- document the exact blocker
- do not fabricate completion

The objective is a clean, secure, installable, testable, end-to-end CausalMesh product integrated through `dev`, with `main` left untouched.
