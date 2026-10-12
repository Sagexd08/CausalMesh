# Claims and leases

Spec §19, §20, §21. Claims are the **enforcement** half of the experiment.
C3 differs from C2 by exactly one thing — before an agent may write to a
path, it must not be blocked by another agent's live claim — so this
mechanism is what makes the C2→C3 contrast measure enforcement rather than
noise.

Status: describes the registry as implemented (Step 4 of `docs/PLAN.md`).
The write gate in the tool layer consults it through the claim rule
(`Gate._rule_claim`, `src/causalmesh/policy/gate.py:373-397`), but only when
the `Gate` is built with a `ClaimRegistry`. The SDK does so when the session
is given `claims=` (`src/causalmesh/sdk/mesh.py:770`); `causalmesh policy
check --stdin`, and so the Claude Code example hook, builds its `Gate`
without one (`src/causalmesh/cli/commands_policy.py:179`), so that path
refuses on declared ownership only. What is and is not built around leases
(fencing, heartbeat, atomic multi-path acquire, cross-machine) is tracked in
`docs/backlog.md` under "Claim enforcement: what the audit of 2026-10-12
found missing"; the status of each claim made for this mechanism is in
`docs/claims-ledger.md`.

## The invariant

> At most one valid writer claim may exist for a path at any instant.

"Valid" means **granted, not released, and not expired**. All three
conditions are evaluated on every read, against a caller-supplied clock.

The invariant is verified three ways, because each falsifies something
different:

| Level | Test | What it can falsify |
|---|---|---|
| Sequential | `tests/unit/test_claims.py` | Ordinary logic errors |
| Threaded | `test_exactly_one_thread_wins_a_contested_path` (2/4/8/16 contenders) | Races inside the transaction boundary |
| **Cross-process** | `test_exactly_one_process_wins_a_contested_path` | A lock that does not survive the process boundary |
| Generated schedules | `test_no_schedule_can_produce_two_live_claims_on_a_path` | Interleavings nobody wrote by hand |

The cross-process level is the one that matters. Agents run as separate OS
processes (§11), so an in-process lock would enforce nothing across the very
boundary the experiment puts them on — a threads-only test could pass with a
mechanism that fails in the real configuration.

## Why SQLite with `BEGIN IMMEDIATE`

§19 requires transactional storage rather than an in-memory lock. The
mechanism is `BEGIN IMMEDIATE`, which takes the database write lock at
statement start rather than on first write. Without it, two callers could
both read "no holder" before either inserted, and both would be granted the
same path.

Two implementation details follow from real failures, not from theory:

**Thread-local connections.** A `sqlite3.Connection` may only be used by the
thread that created it. Passing `check_same_thread=False` would silence the
error while leaving the connection genuinely unsafe under concurrent use, so
each thread gets its own connection and serialization stays where it belongs
— in SQLite's write lock, which works across threads and processes alike.
Every connection is tracked so `close()` can release those opened by threads
that have since finished; without that the registry leaks a file handle per
worker.

**`:memory:` is backed by a temporary file.** A plain in-memory database is
private to its connection, so threads would each get an empty registry and
the exclusivity tests would pass vacuously. The shared-cache in-memory form
fixes that but uses table-level locking that fails immediately with
`database table is locked` instead of honouring the busy timeout — different
behaviour under contention from the file-backed path real runs use. A
temporary file means tests exercise exactly the production code path,
including WAL and the busy timeout.

## Operations

| Operation | Behaviour |
|---|---|
| `acquire` | Grants a lease on a free path; records a denial otherwise. Re-acquisition by the current holder extends rather than conflicts. |
| `renew` | Extends a lease the caller still holds. An **expired** lease cannot be renewed. |
| `release` | Frees the path immediately. Idempotent (§42). |
| `check` | Read-only: the claim blocking a path right now, if any. |
| `may_write` | The C3 write gate. Read-only, so calling it more often cannot change the measurements. |
| `expire` | Sweeps lapsed claims, recording the transition. |

### Design decisions worth stating

**Denials are data, not exceptions.** §20 requires recording who was blocked,
by whom and why. Returning a `ClaimOutcome` keeps that record complete rather
than leaving each call site to decide what to log.

**Re-acquisition by the holder is granted.** An agent asking for a lease it
already owns is not a conflict; counting it as one would inflate the
blocked-write rate that measures enforcement cost.

**Claims are exclusive when held, not mandatory before every write.** A path
with no live holder is writable. This is the specific enforcement C3 defines;
requiring a claim for every write would impose a stricter regime than the
experiment asked for.

**`may_write` never mutates.** The gate is consulted constantly. If it
recorded denials itself, the denial count would depend on how often it was
called rather than on how much real contention occurred.

**Expiry is exclusive at the deadline.** A claim expiring exactly now is
already free, so lease-wait measurements are not off by one instant.

**`EXPIRED` and `RELEASED` stay distinct.** Both free the path, but a lease
that ran out is a coordination signal — the holder was too slow, or crashed —
while a release is orderly completion. Collapsing them would erase that
difference from the §21 measurements.

**Paths are normalized.** Separators are unified and Unicode is
NFC-normalized, so `src/a.py` and `src\a.py` are one resource. Without this
the invariant would silently not hold between agents on different platforms.

**Runs are namespaced.** Claims are scoped by `run_id`, so concurrent runs
sharing a database file cannot block one another — arms must not interfere
(§2).

## Crash recovery

An agent that dies holding a lease does not hold the path forever: the lease
lapses and another agent takes over
(`test_a_crashed_holder_is_taken_over_after_the_lease_lapses`). Correctness
does not depend on a sweep running — `check` and `may_write` evaluate expiry
directly — but `expire` persists the transition so expiries are countable in
the metrics.

An expired lease **cannot** be renewed. Allowing it would let a crashed agent
reclaim a path another agent had legitimately taken over.

## What a denied write guarantees

A denied write never modifies the artifact. Demonstrated on real files by
hashing the target before and after: the gate refuses, the write does not
happen, and the file is byte-identical
(`test_a_denied_write_leaves_the_file_byte_identical`).

Default lease parameters (§21), configurable rather than hard-coded:

```yaml
lease:
  duration_seconds: 120
  renewal_interval_seconds: 30
```

## What this does not do

- **No queueing or fairness.** A denied agent is told who holds the path and
  until when; it is not placed in a queue. Lease-wait time is therefore a
  property of agent retry behaviour, and is measured rather than designed.
- **No configuration is read from the `lease:` block above.** Nothing in
  `src/` reads `duration_seconds` or `renewal_interval_seconds` (a search of
  `src/` for `renewal_interval` finds nothing); the experiment runner takes
  its duration from `RunConfig.lease_us` (`src/causalmesh/tasks/runner.py:72`).
  The block documents the intended §21 defaults, not behaviour.
- **No automatic renewal.** Nothing calls `ClaimRegistry.renew` on a timer
  or on activity (a search of `src/` finds no caller), so a holder that
  works longer than its lease loses the path unless it renews by hand.
- **No fencing tokens.** A holder whose lease lapsed mid-write is not
  stopped at the resource; the registry has no per-resource token that a
  write could be checked against.
- **No atomic multi-path acquire.** `acquire` takes one path. A caller that
  needs several takes them one at a time and can end up holding some.
  Handoff is a `release` followed by an `acquire`, not one transaction.
- **No deadlock detection.** Leases expire, which bounds any wait, but a
  cyclic wait among agents is not detected as such.
- **No cross-machine coordination.** SQLite serializes within one filesystem.
  Distributed operation is out of scope for this slice.
