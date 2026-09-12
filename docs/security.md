# Security model

Spec §87. This document states what the cryptographic layer establishes, what
it does not, and which test demonstrates each claim. Everything listed under
"Protected" corresponds to a passing test; anything not demonstrated by a test
appears under "Not protected", even where a stronger claim would sound better.

Status: describes the implementation as of the crypto/chain layer
(Step 2 of `docs/PLAN.md`). The full attack battery (§58) arrives with the
offline verifier in Step 3; this document will be extended, not rewritten.

## What the chain is

Each event is bound to every event before it:

```
h_0 = SHA256(GENESIS || canonical(event_0))
h_i = SHA256(h_(i-1) || canonical(event_i))
```

`GENESIS` is `SHA256("causalmesh/chain/genesis/v1")` rather than 32 zero bytes,
so a chain produced by a different system cannot validate here. The previous
hash is mixed in as **raw 32 bytes** decoded from hex, not as hex text — an
independent verifier that chose the other convention would compute different
digests, so the convention is pinned in code and in this document.

`h_i` is then signed with the appending actor's Ed25519 private key. The
signature covers the **chain digest**, not the bare event, which means each
signature attests to the entire history up to that point. An event therefore
cannot be lifted from one chain and replayed at a different position with its
signature intact.

Two distinct properties, deliberately kept apart:

| Property | Provided by | What it means |
|---|---|---|
| Tamper-**evidence** | the hash chain | Any change, insertion, deletion or reordering breaks the links. It does not *prevent* tampering; it makes tampering visible. |
| **Attribution** | Ed25519 signatures | Recomputing a digest is free, so a chain alone could be rewritten wholesale. Signing means forging a link also requires the actor's private key. |

## Protected

Each row is demonstrated by a passing test.

| Attack | Detected by | Test |
|---|---|---|
| Event mutation | recomputed digest no longer matches | `test_mutating_the_event_breaks_the_hash`, `test_altering_any_event_invalidates_that_link` (property) |
| Digest forgery after mutation | signature does not verify over the new digest | `test_mutating_the_chain_hash_breaks_the_signature` |
| Relinking to a different predecessor | `previous_hash` is inside the digest | `test_relinking_to_a_different_predecessor_breaks_the_hash` |
| Actor substitution | signature does not verify under the substituted key | `test_substituting_another_actors_public_key_breaks_the_signature` |
| Misattribution at signing time | signing refuses when keypair and `agent_id` disagree | `test_signing_a_peers_event_is_refused` |
| Cross-chain replay | signature covers history, not just the event | `test_signature_covers_history_not_just_the_event` |
| Malformed or garbage records | verification returns `False` rather than raising | `test_corrupt_chain_hash_hex_is_a_failure_not_a_crash`, malformed key/signature cases |

Insertion, deletion and reordering are consequences of the same mechanism —
each shifts the digests of every subsequent link — and are covered end-to-end
by the §58 battery once the offline verifier lands.

## Not protected

Stated plainly, because §87 forbids overclaiming.

### Suffix truncation without an anchor

Dropping events from the **end** of a log leaves a shorter chain that is
internally consistent and fully verifiable. Nothing inside the chain can
detect this. The property test
`test_truncating_a_suffix_leaves_a_self_consistent_chain` asserts the
limitation explicitly rather than leaving it undocumented.

This is the reason anchors (§28) exist: an externally recorded chain head at
sequence *n* makes any truncation below *n* detectable. Until anchoring is
implemented, **maximum unanchored suffix exposure is the entire log.**

### Compromised private key

An attacker holding an actor's private key can produce validly signed events
attributed to that actor. Signatures establish *who signed*, never *whether
what they signed was honest*.

### Shared seed origin

Keys are derived deterministically via HKDF-SHA256 from
`(master_seed, actor_id)` with the fixed info string `causalmesh/ed25519/v1`.
This is required for reproducibility (§40, §84): randomly generated keys would
make a run impossible to reproduce exactly.

The consequence is explicit: **anyone holding the master seed can forge any
actor's signature.** This is acceptable under the threat model below, where the
adversary tampers with recorded evidence after the fact and is not the
operator. Derived keys remain independent of one another — HKDF output is
indistinguishable from random without the seed — so per-actor attribution
stays meaningful *among participants*. A deployment with genuinely mutually
distrusting participants must use `KeyPair.generate` and accept the loss of
exact reproducibility.

### Truthful signature on harmful behaviour

An agent that legitimately signs an event describing a destructive action
produces a valid record. The log proves the action happened and who did it; it
makes no judgement about whether it should have.

### Malicious operator, and unjoined participants

An operator controlling the relay and the master seed can construct any log
they wish before it is anchored. An agent that never joins the relay produces
no events, and its absence is not detectable from the log alone.

## Threat model

**In scope.** After-the-fact tampering with recorded evidence: someone with
write access to `data/raw/` attempting to alter, insert, remove, reorder or
reattribute events so that the analysis draws a different conclusion.

**Out of scope.** A compromised operator, a leaked master seed, and dishonest
behaviour that is honestly recorded.

This scoping is the right one for the research goal. The claim CausalMesh needs
to support is *"these results follow from evidence that has not been edited
since it was produced"*, not *"these agents were trustworthy"*.
