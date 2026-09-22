# CausalMesh — the agentic framework

**Status: proposed, not built.** Written 2026-09-15. Nothing here is implemented.
`docs/PLAN.md` remains authoritative for what exists; this is the plan for what comes
next, kept separate so the two are never confused.

---

## 1. The thesis

Web development has frameworks. Rails, Django, Next — opinionated, convention-driven,
with the guidelines *built into the substrate* rather than written on a wiki. You do
not decide where a model goes or how a route is named; the framework decided, and that
decision is why a new engineer can read any Rails app.

Agentic development has **libraries** (LangChain, CrewAI, AutoGen) and **harnesses**
(Claude Code, Cursor, Codex). It does not have a framework in that sense. Every project
re-derives: which model, how tools are structured, what the context strategy is, how
subagents communicate, who is allowed to write what, who is allowed to *spend* what.

And crucially: **this is not only about coding agents.** Agents now write code, pay for
APIs, settle invoices, and act autonomously for hours. The same three questions apply
to all of them — what did it do, was it allowed to, and can you prove it afterwards.
Nothing answers those questions across all three kinds of agent. That is the framework.

### What if LangChain could be better

LangChain and LangGraph reached v1.0 and became the default. The 2026 criticism is
consistent and specific, and it maps onto what a framework should have decided for you:

| The complaint | What it actually means |
|---|---|
| "42% said nested abstractions hindered development; one change required traversing seven layers" | Abstraction without conventions. Layers, but no opinions. |
| "A Swiss army knife with no prescribed workflows" | It is a library that is sold as a framework. |
| "AutoGen conversation loops are the biggest cost risk — 5–10× expected tokens without hard termination" | No enforced budget. Nothing refuses. |
| "The gap between demo and production traffic is where framework choice matters" | Nothing between the prototype and the incident. |
| "Developers want less abstraction complexity and more production durability" | They want conventions and guarantees, not more surface. |

LangGraph's answer was **durable execution** — state that survives a restart. That is
the right instinct and it is half the problem. Durability says *the work resumes*.
It does not say *the work was allowed*, and it cannot prove afterwards *what happened*.

> LangGraph made agent state durable.
> The missing half is making agent behaviour **accountable**.

A better framework does not out-abstract LangChain. It makes different decisions for
you, and it can prove the decisions were kept.

### The gap is real, and now it is regulated

Six independent 2026 sources describe the same hole from six directions:

| Source | Finding | Implication |
|---|---|---|
| [Governance Gaps in Agent Interop Protocols](https://arxiv.org/pdf/2606.31498) | MCP, A2A and ACP **cannot express**: attribution, verifiable audit trails, provenance, resource-ownership enforcement, conflict resolution, fine-grained access control, enforcement | Reads almost like a spec of what CausalMesh already built |
| [NIST CAISI AI Agent Standards Initiative](https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure) (Feb 2026) | NCCoE paper covers authentication, authorization, auditing, **non-repudiation**; names agents running as generic service accounts that "cannot be audited back to specific user intent" | A US standards body describing our signed chain as a missing control |
| Singapore IMDA Model AI Governance Framework for Agentic AI (Jan 2026) | Requires each agent to carry a **verifiable identity** and an **audit trail of which agent acted under whose authorisation** | Per-agent keys + signed chain, as a regulatory requirement |
| [Trust Without Trusting](https://arxiv.org/pdf/2605.06738) (arXiv 2605.06738) | Proposes a *recomputable* trust protocol: offline re-verification of signed execution traces without trusting the infrastructure | Independently specifies `causalmesh verify` with the relay stopped |
| [OpenTelemetry GenAI conventions](https://opentelemetry.io/blog/2026/genai-observability/) | Standardize agent *tracing*; **explicitly stop before** evaluation, safety scoring, enforcement | The boundary where OTel stops is where we start |
| [AgenticFlict / AIware 2026](https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/) | 142k+ agent PRs, 59k+ repos, **27.67% conflict rate**; cross-agent pairs conflict ~2× intra-agent | Empirical proof the coordination problem is real at scale |

And the layer that *did* standardize proves the point by omission. [AGENTS.md](https://asdlc.io/practices/agents-md-spec/)
is read by Claude Code, Codex, Cursor, Aider, Devin, Copilot, Gemini CLI and Windsurf,
is stewarded at the Linux Foundation, and sits in 60,000+ repositories. It expresses
guidelines and **enforces nothing**. A convention every agent reads and no agent is
held to is exactly a convention without a substrate.

### Why us

Most projects proposing an agent framework start from orchestration and bolt governance
on. We have the inverse — and rarer — half already built and tested:

- an **Ed25519-signed, hash-linked event chain** per run, verifiable offline with the
  relay stopped (28/28 chains verify today)
- a **gate** that refuses an action and records the refusal as evidence
- **declared ownership** driving claims and relevance — nothing inferred from behaviour
- a **four-arm experimental design** that can *measure* whether a convention helps

Nobody else has the fourth. A framework that ships a guideline **and a number proving
the guideline pays for itself** is a different category of product.

> Every other layer tells agents what to do.
> CausalMesh is the layer that can prove what they did, and refuse what they shouldn't.

---

## 2. The architecture

One contract, four planes, three agent kinds. The planes are universal; the agent kinds
are adapters over the same primitives.

```
   coding agents        payment agents       autonomous agents
  (Claude Code,          (x402, MPP,          (long-running,
   Codex, Cursor…)        Stripe…)             scheduled, A2A)
        │                      │                      │
        └──────────────────────┼──────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  CONTRACT           │  causalmesh.yaml
                    │  who / owns / may   │  declared, diffable
                    └──────────┬──────────┘
                    ┌──────────▼──────────┐
                    │  ENFORCEMENT        │  the gate
                    │  allow or refuse    │  refusal is evidence
                    └──────────┬──────────┘
                    ┌──────────▼──────────┐
                    │  EVIDENCE           │  signed chain
                    │  what happened      │  offline-verifiable
                    └──────────┬──────────┘
                    ┌──────────▼──────────┐
                    │  MEASUREMENT        │  the arms
                    │  what it bought     │  the moat
                    └─────────────────────┘
```

**The key insight that makes one framework cover three agent kinds:** a refused write
and a refused payment are the same primitive. A gate that consults declared authority,
denies, and records the denial. `WRITE src/config.py` and `PAY 0.05 USDC to api.x.com`
differ in their payload and in nothing else that matters to the substrate.

### The contract

```yaml
# causalmesh.yaml — sibling to AGENTS.md, not a replacement.
# AGENTS.md says what agents should do. This says what they may do.
version: 1

identity:
  # Per-agent keypairs. Required by IMDA; the chain already signs per-actor.
  keys: .causalmesh/keys/
  attribution: required        # every action traces to an agent and an authoriser

roles:
  - agent_id: agent_a
    archetype: writer
    owns: [src/schema.py, src/models/]
  - agent_id: buyer
    archetype: spender
    budget: { usd_total: 5.00, usd_per_call: 0.10 }
    allow: [api.example.com, data.vendor.io]

policy:
  arm: C3
  contested:
    src/config.py: exclusive
  budgets:
    coordination_bytes: 4096
    wall_clock_s: 600
    tokens: 200000             # the AutoGen 5–10× blowup, refused
  checkpoints:
    - on: payment              # opt out of safety, not into it
      when: { usd: ">0.50" }
      require: human

evidence:
  sign: true
  verify_on_exit: true
  export: [otel, manifest]
```

### The four planes

**1 · Contract.** Ownership, archetypes, budgets, contested paths, spend limits.
Half-built: `roles` and ownership already drive the claim registry; `arm` already
selects a channel and gate. New work is the format, a validator, and `causalmesh init`
that writes one by reading the repo and any existing AGENTS.md.

**2 · Enforcement.** Exists for writes. New work is generalising the gate from *paths*
to *resources*, so a path, an endpoint, a dollar amount and a token budget are all
things that can be owned, claimed and refused. This is the single most important
refactor in the plan — it is what turns a coding tool into a framework.

**3 · Evidence.** Exists and is the strongest asset. New work is making it *portable*:
a proof anyone can verify with no CausalMesh install, and an OTel export so the chain
lands in whatever observability stack a team already runs. We do not compete with
OpenTelemetry; we fill the layer it declines to cover and hand it spans.

**4 · Measurement.** Exists, and is the moat. Any convention the framework proposes can
be run C2 vs C3 and measured. "Exclusive claims on config.py cost 196 bytes per run and
prevented three clobbers" is a sentence no other framework can produce.

### The decision loop

The four planes describe what the gate checks once. Some of what a run needs to
decide does not fit a single allow/refuse check — it is a small set of typed
questions asked repeatedly as the run progresses:

```
classify       what kind of task is this?
select_agent   which agent should act next?
recover        after a failure: retry, switch agent, or escalate?
accept         does the evidence support ACCEPT, REJECT, or HUMAN_REVIEW?
```

`accept` matters most: run completion should never be read directly off an agent's own
"I'm done" — it should be a decision made against evidence (tests passed, diff
conforms, divergence absent), with `REJECT` and `HUMAN_REVIEW` as named alternatives to
`ACCEPT`, not just the absence of success.

**What a typed decision engine in this role looks like, concretely.** TypeSafe AI's Jev
(per the vendor's public announcement, shipped 2026-09-15) takes arbitrary state and a
set of typed questions — Choice (pick one of several named options), Score (rate
against an ordered scale), Noul (the probability a yes/no proposition is true) — and
returns a calibrated answer to each by selection rather than text generation, so it
cannot answer outside the options it was given. `classify`, `select_agent`, `recover`, and `accept` all fit that shape exactly:
each is a fixed, enumerable set of outcomes evaluated against the current run state.
We built and tested a `JevClient` adapter (`src/causalmesh/jev/`) against Jev's real API
to confirm the shape is implementable cheaply today — this is evidence the decision
loop is buildable, not an adopted dependency.

**What exists today.** The adapter, tested unit and against the live API. Nothing in
the runtime calls it. The gate (`policy/gate.py`) remains entirely deterministic rule
evaluation, which is correct for what it decides today — ownership, allowlists,
budgets, and leases all have a single correct answer given the contract, and a
probabilistic call would add latency and a new failure mode without resolving any real
uncertainty. `select_agent` and `recover` have no home yet: the scheduler runs exactly
one agent per run, with no state for "switch to a different agent mid-run." Recovery
producing a signed handoff package — the task, repo state, diff, test results, and
prior decisions, so a second agent inherits execution state rather than starting cold
— is designed here but not built; see `docs/backlog.md`.

---

## 3. The three agent kinds

### Coding agents — where we already are

Eight connectors (Claude Code, Codex, Cursor, OpenCode, Aider, Cline, Goose, Continue),
each marked honestly as exercised or unexercised. `causalmesh connectors verify` probes
each headless interface **without a paid run**. The current two-entry table is right to
be short; the fix is more entries with accurate labels, not optimistic ones.

### Payment agents — the highest-stakes extension

[x402](https://www.allium.so/blog/x402-explained-the-internet-native-payments-standard-for-apis-data-and-agent-commerce/)
went Coinbase → Linux Foundation (Apr 2026), with a 40-member foundation (Jul 2026);
Stripe/Tempo's MPP covers recurring and multi-agent settlement. Real volume is still
thin — ~$28k/day, much of it testing — which means **this is early enough to enter and
the conventions are not yet set.**

An x402 flow is: agent requests → server answers `HTTP 402` with payment instructions →
agent pays → server verifies on-chain → access granted. The gate sits at "agent pays."

```
causalmesh serve --arm C3 --policy causalmesh.yaml

  agent_buyer → GET api.vendor.io/data
  ← 402 Payment Required  0.05 USDC
  gate: allow (within budget 0.05/5.00, host allowlisted)
  → paid, signed into chain @ seq 41

  agent_buyer → GET premium.unknown.io/bulk
  ← 402 Payment Required  2.40 USDC
  gate: REFUSED (host not in allow[], exceeds usd_per_call)
  → refusal signed into chain @ seq 42
```

Why this matters more than writes: a clobbered file is recoverable, a spent dollar is
not. "Payments are the highest-risk action class, yet most teams spend more time on
retry logic than on the financial audit layer." We already *are* the financial audit
layer — we just haven't pointed it at payments.

### Autonomous agents — the long-horizon case

Agents that run for hours, on schedules, delegating to each other. The requirements are
the ones LangGraph identified (durable state, human-in-the-loop, resumability) plus the
ones it did not: *who authorised this, and can you prove it tomorrow*. Our runs are
already resumable because progress lives in the index rather than in the process — the
same property that makes the monitor safe to attach.

---

## 4. Build order

Each step independently shippable; each makes the next cheaper. Nothing requires a live
model or a paid agent run.

**Step 0 — generalise the gate.** Path → resource. A path, an endpoint, a dollar, a
token budget are all ownable, claimable, refusable. Everything else depends on this.
*Least visible, most important.*

**Step A — `causalmesh serve`.** An OpenAI-compatible `/v1/chat/completions` endpoint
fronting the relay. Any OpenAI-compatible client connects; every call passes the gate
and enters the chain. Makes *"keep your agent, change the substrate"* true rather than
marketing — the landing page already claims it and the CLI doesn't have it, which is a
disagreement worth closing first.

**Step B — the interactive TUI.** One app you stay inside: keyboard navigation, launch,
watch, drill into a chain, verify, read contrasts. Built on `rich` (already a
dependency) — not Textual; a second UI framework as a runtime requirement costs more
than it is worth. Foundation is a single-keypress reader (`msvcrt` on Windows,
`termios` elsewhere), drafted this session, not committed. Carries the four features:

- **Replay / time-travel** — scrub a finished run, watch the arms diverge event by
  event to the exact tick where C3 refuses. Possible only because the chain holds every
  event in order. *This is the demo.*
- **Live head-to-head race** — the same task under four arms simultaneously.
- **Cost/benefit ledger** — what coordination cost and bought, in tokens and dollars.
- **Proof you can hand someone** — `causalmesh prove` emits a self-verifying file that
  checks the Ed25519 chain client-side with no CausalMesh install.

**Step C — x402 adapter.** The gate at `HTTP 402`. Budgets, host allowlists, per-call
ceilings, human checkpoints above a threshold. Every payment and every refusal signed.

**Step D — `causalmesh init`.** Reads the repo and any AGENTS.md, proposes a contract,
explains each choice. The Rails `new` moment: the framework decides so the team doesn't.

**Step E — isolation, with agent-escape.** [agent-escape](https://github.com/arpankernel/agent-escape)
(Arpan, Go) is complementary, not competing: it measures whether isolation *holds*; we
measure what coordination *buys*. They meet at our weakest point — C0 isolation on
Windows is layered and **asserted**, not proven, because there is no chroot, a caveat
already in `docs/isolation.md`.

Its `Backend`/`Sandbox` interface (Name/Start/Exec/ReadFile/WriteFile/Stop) and its
canary model are the missing layer. Plant its filesystem canaries in peer workspaces;
treat any canary access during a C0 run as a chain-recorded isolation failure. That
turns a documented caveat into a verified property. Worth talking to Arpan about the
interface before building against it. *(His README's clone URL is stale —
`arpan-mondal` vs the live `arpankernel`.)*

**Step F — SDK.** `@causalmesh/sdk` and `causalmesh` on PyPI, so people build *on* it.
Not before A–E: an SDK over an unstable substrate is a migration you owe everyone later.

---

## 5. Complementary features

**Strong fit — build:**

- **OTel export.** Emit `gen_ai.*` spans from the chain. Meets the standard where it
  exists, occupies the layer it declines to cover, makes us legible to every
  observability vendor at once. Cheap.
- **Compliance export.** One command producing the artifact NIST/IMDA/EU AI Act
  auditors ask for: which agent, under whose authorisation, did what, and the signature
  proving it. We already hold every field; this is a report, not a feature.
- **Naming the three audit properties separately.** "Is the record trustworthy" is
  actually three different questions, and conflating them overstates what one
  guarantee proves:

  | Property | Question | Status today |
  |---|---|---|
  | Integrity | Did the record change after it was written? | Answered — the adversarial battery (`Integrity.jsx` on the landing page) detects 7/7 tamper modes, with suffix truncation named as the one gap an external anchor would close |
  | Provenance | Which signing identity emitted this event? | Answered — Ed25519 per-actor keys, checked on every verify |
  | Completeness | Did instrumentation capture every event a policy requires? | Open — nothing today measures whether the event *policy* itself is exhaustive, only whether the events that were written are intact and attributed |

  A valid signature on every recorded event does not prove nothing was left
  unrecorded. Compliance export should eventually report against all three
  separately rather than implying one covers the others.
- **Conflict prediction.** With a 27.67% empirical conflict rate and declared ownership,
  warn *before* a run that two agents' paths overlap on a hotspot. Static analysis over
  the contract — no model needed.
- **Scenario / Assertion / Consistency eval.** Frozen fixture + task + assertions, run
  N times, report variance. We have frozen fixtures and N repetitions already; mostly
  naming what exists plus a variance report.
- **Budget enforcement with refusal.** The AutoGen 5–10× token blowup, refused and
  recorded rather than discovered on an invoice.

**Right idea, defer:**

- **A2A / MCP adjacency.** A2A v1.0 (Apr 2026, 150+ orgs); MCP ~110M monthly downloads.
  Long-term we want to be the governance layer *under* both — but the governance-gaps
  paper says these protocols cannot express what we enforce, so there is no clean hook
  yet. Watch, don't build.
- **Context budgets and loop detection.** Named as must-have primitives; real, but they
  belong to the harness layer more than the substrate. After Step D.

**Explicitly not:**

- **A new orchestration library.** The world has enough. Our value is underneath them —
  and "works with LangGraph" beats "replaces LangGraph" for years.
- **A hosted control plane.** Local-first, offline-verifiable is the differentiator. A
  SaaS dashboard would undercut the one claim nobody else can make.
- **Our own agent loop.** Every hour spent on a loop is an hour not spent on the only
  four planes nobody else has.

---

## 6. What makes this "holy shit"

Not one feature — a ninety-second sequence:

1. `causalmesh init` reads your repo and writes a contract you can read in one screen.
2. `causalmesh serve --arm C3` — you keep Claude Code, Cursor, whatever you use.
   Nothing about your workflow changes.
3. Your agents run. One tries to write a file another owns. One tries to spend $2.40 on
   an unlisted host. **Both refused**, both refusals signed.
4. `causalmesh replay --latest` — scrub to the exact event; watch three arms clobber
   each other and the fourth not.
5. `causalmesh prove --latest > proof.html` — hand it to someone with no CausalMesh
   install. It verifies itself in their browser.

Steps 4 and 5 are what people repeat to other people. 4 is possible only because of the
chain; 5 only because the chain is signed — so the moat and the demo are the same
artifact.

---

## 7. Open questions

1. **`serve` scope.** Full proxy to a real provider, or gate-and-record with the model
   call passed through untouched? The second is smaller and proves the claim; the first
   is what people will assume it does.
2. **Contract format.** `causalmesh.yaml`, or a section inside AGENTS.md? Riding the
   adopted standard is cheaper to adopt, harder to validate.
3. **How far into payments.** Gate x402 only, or also MPP? x402 is the cleaner protocol
   and has Linux Foundation custody; MPP has Stripe. Doing one well beats both badly.
4. **agent-escape depth.** Vendor the interface, depend on the binary, or adopt only the
   canary idea? Ask Arpan.
5. **Where the four TUI features live.** All inside one app, or standalone commands the
   app also calls? Leaning standalone — testable, scriptable, and the app stays a view.
6. **Naming.** "Arms" and "collections" are experiment vocabulary; a framework has
   "profiles" and "runs". Cheap to change now, expensive after adoption.

---

## Sources

- [Governance Gaps in Agent Interoperability Protocols](https://arxiv.org/pdf/2606.31498)
- [Trust Without Trusting: A Recomputable Trust Protocol for Autonomous Agents](https://arxiv.org/pdf/2605.06738)
- [An Empirical Study of Agent Developer Practices in AI Agent Frameworks](https://arxiv.org/pdf/2512.01939)
- [NIST: Announcing the AI Agent Standards Initiative](https://www.nist.gov/news-events/news/2026/02/announcing-ai-agent-standards-initiative-interoperable-and-secure)
- [Agents Done Right: A Framework Vision for 2026](https://blog.bryanl.dev/posts/agent-framework-vision/)
- [When Agents Collide: 33,596 PRs on Merge Conflicts](https://codex.danielvaughan.com/2026/07/28/agent-pr-merge-conflicts-concurrent-coding-agents-codex-cli-worktree-isolation-coordination-defence/)
- [Inside the LLM Call: GenAI Observability with OpenTelemetry](https://opentelemetry.io/blog/2026/genai-observability/)
- [AGENTS.md Specification](https://asdlc.io/practices/agents-md-spec/)
- [x402 Explained: the internet-native payments standard](https://www.allium.so/blog/x402-explained-the-internet-native-payments-standard-for-apis-data-and-agent-commerce/)
- [Agentic Payments Explained: x402 and MPP](https://aminagroup.com/research/agentic-payments-explained-how-ai-agents-use-crypto-stablecoins-x402-and-mpp/)
- [The Enterprise Guide to AI Agent Audit Trails in 2026](https://www.miniorange.com/blog/ai-agent-audit-trail/)
- [LangChain & LangGraph reach v1.0](https://www.langchain.com/blog/langchain-langgraph-1dot0)
- [The State of Agentic AI Standards in 2026](https://dev.to/alexmercedcoder/the-state-of-agentic-ai-standards-in-2026-mcp-a2a-webmcp-osi-and-the-protocol-stack-taking-3o2l)
- [Why Open Policy Agent is the Missing Guardrail](https://codilime.com/blog/why-use-open-policy-agent-for-your-ai-agents/)
- [AgentEscape](https://github.com/arpankernel/agent-escape) — Arpan
