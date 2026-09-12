# Coordination channels

Spec §14 to §18. A channel is the single point where information enters an
agent. Each arm installs one, so its information behaviour is a property of
the installed object rather than a branch in the runtime — the same
separation the relay uses for delivery and the boundary uses for gates.

```
C0  NullChannel        rejects everything, reports a provable zero
C1  TranscriptChannel  unbounded prose history
C2  MetadataChannel    bounded typed events, at most w per turn
C3  MetadataChannel    identical to C2 — C3 differs by enforcement only
```

C3 sharing C2's channel is deliberate. If C3 also changed representation,
the C2→C3 contrast would confound enforcement with a second factor. The
integration suite asserts the two arms produce **identical per-turn
digests**, which is the strongest available evidence that they saw
byte-for-byte the same context.

## L3: proving C0 received nothing

This is the layer that answers §96's first question. The proof is
arithmetic, not architectural.

Every channel counts the bytes it injects and records a SHA-256 digest per
turn. `NullChannel` reports a permanent zero **and raises** if anything is
ever offered to it. Both halves matter:

- Raising means a bypassed `NullDelivery` policy fails loudly at the moment
  it happens, rather than producing a run that looks valid while being
  contaminated.
- The zero-valued accounting means the C0 claim is checked rather than
  inferred from the absence of wiring. An arm that received nothing because
  someone forgot to connect it looks identical, in the data, to one that
  received nothing by design.

`received_no_coordination` requires **all three** of zero bytes, zero events
injected and zero events available. Bytes alone would pass for an
empty-but-attempted injection; availability alone would miss a channel
injecting something it invented.

Every C0 turn records the digest of the empty string
(`e3b0c442…`), so a C0 run carries a positive audit trail rather than an
empty one that proves nothing.

## §18: availability is not injection

Four counts are kept apart on every turn:

| Count | Meaning |
|---|---|
| `events_available` | delivered by the relay |
| `events_selected` | scored and ranked |
| `events_injected` | actually placed in context (at most `w`) |
| `events_dropped` | available but excluded by the window |

Collapsing these would make "the agent was never told" indistinguishable
from "the agent was told but the window cut it" — conclusions that differ
sharply when explaining why an arm underperformed.

Events dropped by one turn's window stay **pending** rather than being
discarded: a dropped event may be the most relevant one next turn, and
discarding it would be silent information loss.

## Relevance (§17)

Selection is arithmetic, not learned. Five weighted components:

```
path_overlap        0.40   touches a path the agent owns or has edited
dependency_overlap  0.25   touches a declared dependency  (the §23 stale case)
causal_distance     0.15   follows something the agent has already seen
recency             0.10   1 / (1 + age in turns)
priority            0.10   mutating events outrank reads
```

Three reasons for arithmetic over a model:

- **Reproducibility.** The same inputs must give the same ranking, or a run
  cannot be reproduced from its seed (§40, §84).
- **Attribution.** If C2 beats C0, the benefit must be attributable to
  *information*, not to a ranking function doing unmeasured work.
- **Inspectability.** Every score is recomputable by hand from its recorded
  components, and a test asserts exactly that.

Components are stored individually, not just the total: 0.71 from path
overlap and 0.71 from recency mean very different things.

Ties break on `event_id`, never on list position — delivery order varies
with timing, and a selection depending on it would not be reproducible.

Interests are **declared by the task**, not inferred from behaviour.
Inferring them would make the information an agent receives depend on what
it has already done, coupling the manipulation to the outcome.

## Measured cost growth

Fitted from the implementation, not assumed. One new event per turn, `w = 8`:

| T | C0 | C2 | C1 | C1/C2 |
|---:|---:|---:|---:|---:|
| 1 | 0 | 13 | 9 | 0.69 |
| 5 | 0 | 65 | 135 | 2.08 |
| 10 | 0 | 130 | 495 | 3.81 |
| 20 | 0 | 260 | 1890 | 7.27 |
| 60 | 0 | 780 | 16470 | 21.12 |

C1 follows `mu * T(T+1)/2` with **mu = 9.000 and zero error at every T**.

### A correction worth recording

§46 states transcript cost as `C_tr(T) = mu * T(T-1)/2`. That form counts
**pairwise exchanges among T agents**. What these channels measure is
cumulative injected cost over **T turns** with one message each; turn *t*
replays *t+1* messages because the newly arrived event is part of that
turn's history, giving `mu * T(T+1)/2`.

Both are quadratic and both express C1's defining property, but they are
different quantities. Fitting the wrong one produces a 65% error at T=2,
converging to zero only as T grows — which is exactly how a refit-per-point
analysis can make a wrong model look correct. `test_channel_cost_growth.py`
fits `mu` **once** and checks it against every T for this reason.

The analysis module (§46) must implement the spec's agent-pairwise form for
its analytical curves and must not substitute this turn-based one.

### The counter-intuitive part

C2's structured rendering is **larger per event** than C1's prose:

```
C1  35 bytes   "I wrote to src/schema.py."
C2  50 bytes   "seq=0 actor=agent_a type=WRITE paths=src/schema.py"
```

C2's advantage is not compactness — it is that C1 replays the entire history
every turn while C2 injects at most `w`. The crossover is early (T* ≈ 4
turns here) but real, and a test pins the mechanism explicitly so a change
that destroyed it cannot pass by satisfying a compactness assertion instead.

## Token estimation

`estimate_tokens` is an **estimator, not a tokenizer**: roughly four
characters per token. No model runs in the mock-agent configuration, so
there is no authoritative tokenizer to consult.

Its bias is documented rather than hidden — it overcounts on repetitive
structured JSON, which BPE compresses well, and undercounts on dense
identifiers. What the experiment needs is that the estimator be
deterministic and **identical across arms**, since the C1→C2 contrast is a
ratio measured the same way on both sides, so a constant multiplicative bias
cancels.

An absolute token count from this module should not be quoted as a model's
true usage.

## No silent truncation (§15)

C1 applies no truncation, summarisation or deduplication. Each is a
plausible engineering improvement and each would flatten the very curve the
experiment exists to observe. Any limit must appear in configuration and in
the manifest; there is none.
