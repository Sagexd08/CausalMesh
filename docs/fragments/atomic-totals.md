### Totals are reserved, then committed: built, with these limits

**Status: built (2026-09-30).** This replaces two limits that "Non-path resources
through the SDK" listed: that totals were check-then-record, and that a raising
handler was never counted. A declared total (`usd_total`, `tokens`, ...) is now
**reserved** before the handler runs and settled after it.

**What was built.**

- `Ledger.reserve` sums recorded consumption plus live holds, compares the result
  with the limit and inserts the hold in one `BEGIN IMMEDIATE` transaction, so
  callers racing on one allowance are admitted one at a time against the true
  remainder, across threads and across processes. A refusal is returned as data
  (`ReserveOutcome`, with the `spent` and `held` the transaction saw).
  `commit` turns a hold into an entry and `release` drops it; each is a single
  transaction. The holds live in a `reservation` table created on open, so an
  existing ledger file needs no migration. `Ledger.total` is unchanged (recorded
  consumption only); `held` and `release_all` are new.
- `Gate.check(..., holds=[])` takes the reservation inside the budget rule and
  appends it to `holds`. A refusal anywhere in the same check, and any refusal
  of a later resource in the same call, releases what that call had taken, so
  a refused call holds nothing. Without `holds`, `check` is still a read-only
  question, but it now counts live holds as well as recorded spend.
- `ToolGateway` reserves through the gate, then commits when the handler returns,
  releases when it raises, and releases on an interrupt or cancellation (which
  propagates). `GatewayResult`, `Ledger.record` and the ledger's `entries` are
  unchanged. The gateway also serialises event emission (the id counter and
  the relay), which the first concurrent callers showed was not safe; the
  handler and the reservation run concurrently. `serve` still executes serially.
- **A raising handler is released by default, and a tool can say otherwise.**
  `Tool(..., spend_on_error=True)` counts the amount as spent when the handler
  raises, for a tool that cannot tell whether the money left. The default
  under-counts (a failure before the money moved is not charged); the opt-in
  over-counts (a failure that never spent is). Neither is right for every tool,
  which is why it is the tool's declaration and not the gateway's guess. The
  result is still a failure either way.

**Tested.** 120 threads against a 50-call total: exactly 50 run, 70 are refused
on `budget`, the handler runs 50 times, the recorded total is exactly 5.00 and
no hold is left. A watcher thread asserts recorded plus held never exceeds the
cap mid-race. Four spawned processes on one ledger file are granted exactly 50
holds between them. Reverting the reservation in the gate (back to
check-then-record) lets all 120 run and fails the race tests; changing
`BEGIN IMMEDIATE` to a deferred `BEGIN` fails them too.

**Limits that remain, stated rather than hidden:**

- A holder that dies between reserve and settle leaves its hold behind. That
  over-counts, which fails closed, until an operator runs `Ledger.release_all`
  (safe only when nothing in the run is executing). There is no expiry, because
  any timeout shorter than the slowest handler would release money that is still
  in flight. No CLI command exposes `release_all` yet.
- A hold whose `commit` fails (a ledger that cannot be written) stays counted and
  is reported on `result.audit_error`; the call's outcome stands.
- The reservation exists only on the SDK path. Callers that use `Gate.check`
  directly (`causalmesh policy check`, the x402 adapter, `serve`'s upstream check)
  still ask a question and record afterwards; they see in-flight holds but do not
  take one. The x402 adapter's check-then-pay is therefore still racy for a caller
  that pays outside the gateway.
- Interrupt and cancellation release the hold even if the money had already
  left; `spend_on_error` covers exceptions only.
- The unenforced arms (C0 to C2) take the hold whatever the total, so they record
  what they spend; the refusal they would have made is reported as before.
- Concurrency stops at the ledger and the emit lock: `ContractGate.verdicts` is
  a shared list, so the "would have refused" report on a result can name a
  concurrent call's verdict under C0 to C2. Enforced arms do not read it.
- A reservation is taken per resource, in call order. A call that declares the same
  destination twice reserves twice, as it records twice.
- Serial `serve` bounds throughput at one call at a time; nothing here changes
  that, since the gateway's handler concurrency is only reachable to a library caller.
