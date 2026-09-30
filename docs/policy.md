# The policy plane

**Status: built and tested.** 88 tests across `tests/unit/test_policy.py`,
`test_policy_gate.py` and `test_checkpoints.py`; wired into the run loop by
`ContractGate` (`hooks/policy_gate.py`), installed automatically whenever
`causalmesh experiment run` or `causalmesh serve` discovers a
`causalmesh.yaml`. What is *not* built is named in "What this does not do
yet" at the end, rather than left as a silent gap.

---

## What it is

Three pieces, in the order a decision moves through them:

| Piece | File | What it does |
|---|---|---|
| `Contract` | `policy/contract.py` | The declared rules, read from `causalmesh.yaml` |
| `Gate` | `policy/gate.py` | Consults the contract, returns a `Verdict` |
| `Ledger` | `policy/ledger.py` | What has been consumed, shared across processes |

And the type that makes them one plane rather than three:

| `Resource` | `policy/resource.py` | A kind plus an identity — the one thing a gate can refuse |

## The idea it rests on

A refused write and a refused payment are the same event. In both cases a gate
consults declared authority, denies, and records the denial with its reason.
They differ in payload and in nothing the substrate cares about.

That is not a metaphor. `ClaimRegistry` was written for file paths, treats
`path` as an opaque normalized string, and was **not modified** to support
payments — it holds an exclusive lease on `spend:api.example.com` because a
resource identity is an opaque normalized string either way. The test proving
it is `test_a_payment_can_be_leased_like_a_path`.

Four kinds, closed deliberately:

- `path` — a file. The built and measured case.
- `spend` — money leaving the operator's account.
- `endpoint` — a network destination.
- `budget` — a consumable allowance: tokens, seconds, bytes.

A wrong kind raises. An open set would let `paymnt:` silently create a
resource nobody holds and nobody refuses, which is the defect class recorded
in `docs/backlog.md`: a confident zero rather than a loud failure.

## The contract

`causalmesh.yaml` sits at the repository root, beside `AGENTS.md`. The two are
siblings on purpose: **AGENTS.md says what agents should do and is enforced by
nothing; this says what they may do, and the gate holds them to it.**

```yaml
version: 1

roles:
  - agent_id: agent_a
    archetype: writer
    owns: [src/schema.py, src/models/]
  - agent_id: buyer
    archetype: spender
    allow: [api.example.com]
    budget:
      usd_total: "5.00"
      usd_per_call: "0.10"

policy:
  arm: C3
  contested:
    src/config.py: exclusive
  budgets:
    tokens: 200000

evidence:
  sign: true
```

Three rules govern how it is read:

**Declared, never inferred.** A rule derived from what agents did cannot
refuse that behaviour.

**Absent means unrestricted; present means enforced.** A role with no
`allow` may reach anywhere; a role with `allow: []` may reach nowhere. This is
what makes adoption incremental rather than a rewrite — you declare the parts
you care about and the rest keeps working.

**Unknown keys are errors.** A typo in `budgets` that parses as nothing is a
budget that does not exist. The message names the valid neighbours.

## The rules, in the order they may refuse

Cheapest and most specific first, so an agent is told "you do not own this"
rather than "someone is currently editing it" when both are true.

| Rule | Kinds | Refuses when |
|---|---|---|
| `ownership` | `path` | Another agent declared `owns` over this path |
| `allowlist` | `spend`, `endpoint` | The host is not in the role's `allow` |
| `ceiling` | `spend` | One call exceeds `usd_per_call` |
| `budget` | `spend`, `budget` | Recorded consumption plus this would exceed the total |
| `claim` | `path`, `spend` | Another agent holds a live exclusive lease |

`ceiling` and `budget` are separate because they fail differently: a total
catches a slow drain, a ceiling catches one catastrophic call. A system with
only a total discovers the mistake after it has been made.

### Two matches that must not be loose

**Allowlists match on label boundaries.** `example.com` covers
`api.example.com` and must *not* cover `notexample.com` or
`example.com.evil.io`. A naive `endswith` lets all of those through, which is
how an allowlist silently fails open.

**Ownership matches on segment boundaries.** `src/app` covers
`src/app/main.py` and must *not* cover `src/application.py`. A prefix test
without this claims a neighbour's file.

Both are parameterised tests, with the failing spellings listed.

## Money is Decimal, end to end

A float budget drifts by fractions of a cent until it silently does not hold.
So a float amount is **rejected at the call site that introduced it**, ledger
amounts are stored as strings, and totals are summed as `Decimal` in Python
rather than in SQL — SQLite would coerce the column to a float to add it,
reintroducing exactly the imprecision the string storage exists to avoid.

`test_the_total_holds_exactly_at_the_limit` spends 0.05 one hundred times and
asserts the total is exactly 5.00 and that the hundredth spend is allowed.
Float arithmetic reaches 5.000000000000004 and refuses a spend that is within
budget.

## The ledger is shared, not counted

Agents run as separate OS processes. A per-process tally would let each one
spend the whole budget, and the total would be exceeded by the number of
agents — silently, because every process would believe it was within limits.
So consumption is SQLite with WAL, for the same reason the claim registry is.

Only actions that **happened** are recorded. A gate check that refused writes
nothing, and a gate check that allowed writes nothing either; the caller
records after acting.

A caller that is about to act on a declared total does not check and then
record, because two callers can both pass the check before either records.
`Gate.check(..., holds=[])` **reserves** the amount in the same ledger
transaction that compares it to the limit (`Ledger.reserve`, `BEGIN
IMMEDIATE`); the caller then `commit`s the hold when the action happened or
`release`s it when it did not. The SDK does this for every `spend` and `budget`
tool (`Tool(..., spend_on_error=True)` counts the amount as spent when a handler
raises; by default it is released). A holder that dies between reserve and settle
leaves its hold, which over-counts until `Ledger.release_all`; `Gate.check` called
directly (`policy check`, the x402 adapter) asks a question and does not reserve.
`total` is still only what happened, and the gate counts recorded plus
held, so a plain `check` does not admit a call an in-flight one has already
claimed the room for. That keeps totals measuring work done rather than
questions asked — the distinction `may_write` and `record_denial` already draw
in the claim registry, and the reason an earlier build reported a confident
zero for enforcement.

## Enforcement isolates exactly one factor

`Gate(enforcing=False)` is the C0/C1/C2 case. The gate still evaluates and
still reaches a verdict; it simply does not act on it, and returns the shadow
verdict in `detail["would_refuse"]` with the rule and reason intact.

That is what makes the C2 → C3 contrast measure *enforcement* rather than a
difference in how two arms were implemented: the same code path runs in both,
and only the verdict differs. It also means an unenforced arm can report what
enforcement would have cost it.

## Using it

```
causalmesh policy init                 # write a starter contract
causalmesh policy show                 # print it as the gate understands it
causalmesh policy check --agent buyer --kind spend \
    --name premium.unknown.io --amount 2.40
```

```
REFUSE  2.40 USD -> premium.unknown.io
        allowlist  'premium.unknown.io' is not in the allowlist for 'buyer'
```

`check` exits 0 when allowed and 1 when refused, so a script can branch
without parsing. It **records nothing** — it is a question about the declared
contract, asked without a run, and a denial count that included questions
would measure how often the gate was consulted.

`--json` on every command.

## What this does not do yet

- **A real x402 payment signer.** `adapters/x402.py` parses a real `HTTP 402`
  challenge into a `Resource.spend` and asks the gate, returning a typed
  `PaymentDecision` — the gate-and-parse half is built and tested against the
  reference `x402` schemas. What is missing is the other half: signing and
  sending the payment. That needs a signer for one of x402's payment schemes
  and networks, a real runtime dependency this project has never carried
  (see `docs/backlog.md`, "Spend is enforced, but nothing speaks x402").
- **A real human-attached checkpoint handler.** `policy.checkpoints` is
  enforced (`policy/checkpoints.py`, `Gate.check`), decided by a
  `CheckpointHandler`, and recorded as `EventType.CHECKPOINT_DECIDED`. The
  default (`AutoDenyHandler`) and the reproducible one (`ScriptedHandler`)
  ship; nothing here prompts an actual person, and the CLI does not surface a
  pending checkpoint.
- **Per-agent external keys are loaded, not generated on demand.**
  `identity.keys` (`crypto.load_identity_keys`) reads a keyed operator's own
  pre-existing files; nothing in this build helps an operator generate that
  directory in the first place.
