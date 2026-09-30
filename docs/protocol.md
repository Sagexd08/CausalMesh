# The relay protocol

Spec §55. The relay is the single point through which every event enters the
record. Everything downstream — verification, metrics, analysis, the report —
depends on the record being complete and unedited, so the relay's restraint
matters as much as its function.

Status: describes the relay as implemented (Step 5 of `docs/PLAN.md`). The
channel layer that shapes *what an agent sees* (§15–§18) arrives in Step 7;
this document covers delivery, not representation.

## What the relay owns

| Responsibility | Why the relay and not the agent |
|---|---|
| Sequence assignment | An agent-chosen sequence would let a fast agent claim an earlier position than it earned, misrepresenting the causality the staleness measurement (§23) depends on |
| Signing and chaining | Makes the log tamper-evident by construction rather than by convention |
| Persistence | One append-only writer, so there is no path by which raw evidence gets rewritten (§31) |
| Fan-out | Puts "who can see what" in exactly one place instead of scattering it through the runtime |

## What the relay must not do

- modify agent code or reasoning
- judge whether a task was completed correctly
- rewrite, repair or drop an event it has accepted

The last restraint is the important one. **An event is either accepted as
given or rejected loudly.** A relay that silently corrected a malformed event
would be editing evidence, so ingestion validates and refuses rather than
normalising.

Four rejections, each protecting a specific property:

| Rejection | Protects |
|---|---|
| Unregistered actor | Attribution — an event nobody can be shown to have signed |
| Identity ≠ submitter | Attribution — refusing to record work credited to the wrong agent |
| Wrong `run_id` | Arm separation (§2) — arms must never share a chain |
| Duplicate `event_id` | Idempotency (§42) |
| Structurally invalid event | The record's integrity, without silent repair |

A rejected event leaves no trace in the chain: the head does not advance and
the sequence does not increment (`test_rejections_do_not_advance_the_chain`).

## Delivery policies: where the manipulation lives

The relay does **not** know about experimental arms. It is handed a
`DeliveryPolicy` and asks it who should receive each event.

```
C0   NullDelivery        nothing reaches anyone
C1   BroadcastDelivery   every peer sees every event
C2   BroadcastDelivery   every peer sees every event
C3   BroadcastDelivery   as C2; the difference is the claim gate
```

This separation is what makes C0's isolation checkable. It is a property of
*which object was installed*, not of a conditional buried in the ingestion
path that could be reached by accident.

The informed arms can be run with path-scoped delivery instead of broadcast
(`policy_for_arm(arm, mode="path_scoped", interests=...)`, or
`RunConfig.delivery_mode`). This is used by the scalability profile
(`causalmesh experiment scalability`) only; the four primary arms are
broadcast. C0 is `NullDelivery` in every mode. Path-scoped delivery hands an
agent exactly the events whose paths intersect its declared interests, and every
path-less event to everyone; asking for it without an interest map raises
rather than falling back to broadcast. What that measured, and the limits, are in
`docs/backlog.md` ("Scaling beyond 4 agents").

`policy_for_arm` raises on an unknown arm rather than defaulting. A silent
default could hand C0 a broadcast policy and destroy the isolation the whole
experiment rests on.

**C1 and C2 deliberately share a fan-out policy.** They differ in
*representation* — unbounded transcript versus bounded typed metadata — which
the channel layer handles. Making them differ in delivery too would turn the
C1→C2 contrast into a measurement of delivery differences instead of the
representational difference it is designed to isolate.

Relevance filtering and windowing (§17, §18) also belong to the channel layer,
not here. Filtering at fan-out would drop events with no trace, and §18
requires "not available" to stay distinguishable from "available but not
injected".

An agent is never delivered its own event: it already knows, and counting it
would inflate coordination volume.

## Concurrency

A single lock serializes ingestion so that sequence assignment and chain
extension cannot interleave. Two events sharing a sequence number, or a link
computed against a stale head, would corrupt the record irrecoverably — and
unlike a claim conflict, there would be no denial record to reveal it
afterwards. `test_concurrent_ingestion_produces_a_valid_chain` drives 24
events through 8 threads and verifies the resulting chain.

## Storage

`ChainStore` is append-only, and enforces that by **offering no mutation API
at all** — no update, delete, replace or clear. §31 forbids analysis from
modifying `data/raw/`, and the cheapest guarantee is code that cannot express
the operation (`test_the_store_exposes_no_mutation_api`).

JSONL, one record per line, flushed per record. A crash mid-run leaves a
truncated final line rather than a corrupted file, and every complete line
before it stays verifiable. A single JSON array would need rewriting on every
append and would be unreadable if the process died before closing the bracket.
`fsync` is optional: it dominates run time, and a lost final event shows up as
a short chain rather than as silent corruption.

Opening a store on a file that already has content is refused — a run's raw
log belongs to exactly one run.

## Export

`relay.export()` writes two files:

```
chain.jsonl     the signed chain
keyring.json    the public keys
```

That is everything the offline verifier needs (§26, §82). Nothing in the
export refers back to the relay.

## Self-measurement

§85 forbids claiming the coordination mechanism is cheap without measuring it,
so the relay measures itself: events ingested and rejected, delivery count,
and append-latency p50/p99.

Percentiles report `None` rather than `0` when nothing has been measured, so
"no measurements" stays distinguishable from "measured zero".

## How the arm guarantees are tested

`tests/integration/test_arm_isolation.py` runs **one scripted history through
all four arms** and compares the results, rather than checking each arm alone.
An arm accidentally differing in a third factor would be invisible to
single-arm tests.

The C0 isolation test was initially vacuous: it asserted that C0 records no
causal parents, but the script never set parents in *any* arm, so it would
have passed with isolation completely broken. It now asserts the informed arms
**do** record parents, so the comparison discriminates. Verified by mutation:
replacing C0's `NullDelivery` with `BroadcastDelivery` fails
`test_c0_receives_no_coordination_data` immediately.

What is provable at this layer today is **delivery and enforcement**. The
representational difference between C1 and C2 is a channel-layer property and
is not yet demonstrated; this document will be extended when Step 7 lands
rather than claiming it early.
