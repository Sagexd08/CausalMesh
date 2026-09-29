# Security model

Spec §87. This document states what the cryptographic layer establishes, what
it does not, and which test demonstrates each claim. Everything listed under
"Protected" corresponds to a passing test; anything not demonstrated by a test
appears under "Not protected", even where a stronger claim would sound better.

Status: describes the implementation as of the offline verifier and its
attack battery (Steps 2–3 of `docs/PLAN.md`). Every row in the tables below
corresponds to a test in the suite (`python scripts/check.py` runs it).

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

| Attack (§58) | Detected as | Test |
|---|---|---|
| Event mutation | `chain_break` | `test_changing_a_path_is_detected`, `test_changing_an_event_type_is_detected`, `test_changing_a_timestamp_is_detected` |
| Mutation with recomputed digests | `signature_invalid` | `test_mutation_with_recomputed_digest_is_still_detected` |
| Event insertion | `chain_break` / `ordering_invalid` | `test_inserting_a_forged_event_is_detected` |
| Replay of a genuinely signed event | `chain_break` / `ordering_invalid` | `test_inserting_a_validly_signed_event_from_elsewhere_is_detected` |
| Duplicate replay | `duplicate_event_id` | `test_duplicate_replay_is_detected` |
| Event deletion | `chain_break` / `ordering_invalid` | `test_deleting_any_interior_event_is_detected` (all interior positions) |
| Event reordering | `chain_break` / `ordering_invalid` | `test_swapping_two_adjacent_events_is_detected`, `test_reversing_the_whole_chain_is_detected` |
| Non-consensual attribution | `chain_break` / `key_mismatch` | `test_reassigning_an_event_to_another_actor_is_detected` |
| Attribution with a swapped key | `signature_invalid` | `test_reassigning_with_a_swapped_public_key_is_detected` |
| Signature substitution | `signature_invalid` | `test_signature_substitution_is_detected` |
| Event from an unjoined actor | `unknown_actor` | `test_an_event_from_an_unknown_actor_is_detected` |
| Prefix removal | `chain_break` | `test_a_chain_not_starting_at_genesis_is_detected` |
| Anchor mismatch | `anchor_mismatch` | `test_anchor_mismatch_is_detected` |
| Malformed or garbage records | `malformed_record`, never a crash | `test_malformed_records_are_reported_not_crashed` |

Mutation is worth spelling out, because it forces the attacker into a choice
with no third branch:

- keep the recorded digest, and recomputation exposes the edited content
  (`chain_break`);
- recompute the digest to match, and the signature no longer verifies
  (`signature_invalid`), which requires the actor's private key to repair.

Both branches are covered above, which is why a single reported failure is
sufficient detection rather than a partial one.

### Attribution is checked against the key ring, not the record

Each record carries the signer's public key, but the verifier never trusts
it. It looks the actor up in the supplied key ring and verifies against
*that* key, reporting `key_mismatch` when the two disagree. Trusting the
embedded key would be circular: an attacker re-signing an event with their
own key would simply rewrite that field too, and the log would verify
perfectly while crediting the wrong actor.

### Damage is localized, not cascaded

The verifier advances on each record's recorded digest, so a single edited
event is reported once at its own index rather than invalidating every later
link. How much of a log survived is itself a finding
(`test_one_corrupt_link_does_not_cascade`).

## Not protected

Stated plainly, because §87 forbids overclaiming.

### Suffix truncation without an anchor

Dropping events from the **end** of a log leaves a shorter chain that is
internally consistent and fully verifiable. Nothing inside the chain can
detect this. Two tests assert the limitation rather than leaving it
undocumented: `test_truncating_a_suffix_leaves_a_self_consistent_chain`
(property) and `test_truncation_is_undetected_without_an_anchor`
(adversarial).

Anchors (§28) close the gap. An externally recorded chain head at sequence
*n* makes any truncation below *n* detectable, reported as
`anchor_missing_event` (`test_truncation_is_detected_with_an_anchor`).

Every verification result therefore reports `unanchored_suffix`: the number
of trailing events no anchor protects. With no anchors it equals the whole
log; with a mid-chain anchor it is the count after the highest matching one
(`test_partial_anchoring_reports_the_exposed_suffix`). The exposure is
measured and reported rather than assumed to be zero.

Note the asymmetry: removing events from the **start** of a log *is* caught,
because the first link no longer joins to genesis. Only the suffix is
vulnerable.

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

## The gateway and `causalmesh serve`

Added after the chain layer above, and covered by separate tests. Same rule:
a row is only here if a test runs it.

| Property | Test |
|---|---|
| A denied mutating call never runs the handler (sync) | `tests/gateway/test_deny.py::TestHandlerNeverCalled`, `tests/gateway/test_async_gateway.py::test_sync_deny_gate_handler_never_called` |
| A denied async call never awaits the handler | `tests/gateway/test_async_gateway.py::test_async_deny_gate_handler_never_awaited` |
| An agent with no signing key is refused before the gate or handler | `tests/sdk/test_evidence.py::TestEveryDeclaredAgentIsRecorded` |
| A declared `resource_args` name that is absent fails closed | `tests/gateway/test_resolver.py::TestMissingResourceFailsClosed` |
| Without `--dev`, `/v1/tools` and `/v1/chat/completions` refuse a missing or wrong bearer token | `tests/server/test_auth.py`, `tests/server/test_openai_compat.py` |
| `--dev` is refused for a non-localhost host; a token is required otherwise | `tests/integration/test_serve.py::TestCliWiring` |
| A blank or whitespace `--api-token` is treated as no token, never as auth-off (found and fixed 2026-09-30; mutation-checked) | `tests/integration/test_serve.py::TestCliWiring::test_a_blank_token_is_no_token_and_never_disables_auth` |
| An unhandled error on `/execute` returns a generic 500 with no exception text or traceback | `tests/server/test_errors.py::test_an_unhandled_error_is_a_generic_500_without_detail` (execute route only; other routes share the handler but are not separately tested) |

Not protected:

- **Reads.** A tool registered `mutating=False` bypasses the gate by design.
- **Unenforced arms.** On C0-C2 the gate records what C3 would refuse and
  allows the call (`result.would_refuse`).
- **`/v1/chat/completions` evidence.** It ignores the relay's ingest result,
  so a request naming an undeclared `causalmesh_agent` is still gated but its
  event is silently not recorded, unlike `/v1/tools/{name}/execute`, which
  reports `recorded` and `audit_error`.
- **Key custody in SDK sessions.** With `seed=`, anyone holding the seed can
  sign as any agent. Without it, keys are random per session and the chain is
  not reproducible.
- **Transport.** `serve` speaks plain HTTP; TLS is the operator's proxy.
  The bearer token is a single shared secret compared as a set member, not a
  per-agent identity.
- **The Docker image** binds `0.0.0.0` and therefore requires
  `CAUSALMESH_API_TOKEN`; it is not a sandbox for the tools registered in it.

## Verification is offline by construction

§26 and §82 require that evidence be checkable without the system that
produced it. The verifier's entire input is a chain file, a public key ring
and optional anchors — three files. It imports only `causalmesh.events` and
`causalmesh.crypto`, and never the relay, the scheduler or the storage layer.

Both halves are enforced mechanically rather than by convention:
`test_the_verifier_does_not_import_the_relay` asserts the import boundary in
a clean interpreter, and the clean-room suite verifies real exported files
from a **separate process in an unrelated working directory**, including
detecting an on-disk tamper introduced there.

## Threat model

**In scope.** After-the-fact tampering with recorded evidence: someone with
write access to `data/raw/` attempting to alter, insert, remove, reorder or
reattribute events so that the analysis draws a different conclusion.

**Out of scope.** A compromised operator, a leaked master seed, and dishonest
behaviour that is honestly recorded.

This scoping is the right one for the research goal. The claim CausalMesh needs
to support is *"these results follow from evidence that has not been edited
since it was produced"*, not *"these agents were trustworthy"*.
