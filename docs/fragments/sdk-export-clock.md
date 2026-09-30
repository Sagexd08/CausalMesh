## SDK export and logical clock (2026-09-30)

Closes two items under "Developer SDK (Phase 1)" / "What does not ship":
**Persistence** and **Wall-clock timestamps in the signed chain**.

### Export

**Status: built, for the SDK session. Not built for `serve`.**

- `CausalMesh.export(directory)` writes `run.json` (the signed `chain`, `arm`,
  `run_id`, `head_hash`, plus an unsigned `envelope`) and `keyring.json`
  (public keys only; a test checks that no seed or private key appears in
  either file). `causalmesh verify --run <directory>` reads it with no
  changes to its input format.
- `causalmesh verify` now prefers a `keyring.json` beside `run.json` to the
  public keys embedded in the records. The old behaviour is unchanged when the
  file is absent. A `keyring.json` that is present but unreadable or malformed
  **fails** the run instead of falling back, because the fallback is the weaker
  check. The result reports which source was used (`keys`: `keyring.json` or
  `embedded`).
- Tests run the real verifier through the CLI: a clean export verifies; a
  changed event and a dropped event fail; a chain re-signed under a foreign
  seed (a second session making the same calls) **fails against the
  keyring**. The same forged chain with `keyring.json` deleted still
  **passes**, and a test pins that as the known limit rather than hiding it.
  Reverting the CLI change makes the foreign-key tests fail.
- `export` refuses to write over an existing `run.json` (raw evidence is
  written once, as the scheduler does) and over a `keyring.json` with
  different keys.
- Opt-in `persist_to=<dir>`: the relay appends `chain.jsonl` as it goes
  (flushed per event, the existing `ChainStore`) and `keyring.json` is written
  at construction. It refuses a directory that already holds a chain.
  `CausalMesh.close()` closes the file.

**What remains.**

- **The keyring is only as good as its channel.** `keyring.json` sits beside
  the run it vouches for, so whoever can replace `run.json` and
  `keyring.json` together can forge both. It protects against a chain re-signed
  by someone who does not control the keyring, which is the auditor who is
  handed the ring separately or pins `key_ring_fingerprint`. Nothing pins the
  fingerprint automatically; `verify` has no `--keyring` option to supply a
  ring from elsewhere. Not built.
- **A crash leaves `chain.jsonl` and `keyring.json`, not `run.json`.**
  `verify --run` reads only `run.json`, so a persisted-but-never-exported
  session cannot be verified by the CLI. There is no `recover`/`export-from-
  chain` command.
- `export` is a snapshot of the in-memory relay, and its envelope's per-event
  wall times are in memory only: a session reopened from `chain.jsonl` has
  none (they are `unknown`, absent from the map, not zero).
- `serve` has no export endpoint or shutdown hook that calls `export`.
- No `--keyring` or fingerprint check exists for experiment runs (`--id`,
  `--all`); those still use embedded keys unless a `keyring.json` was placed
  beside a run by hand.

### Logical clock

**Status: built for the gateway, so for the SDK and for `serve`'s `/execute`.
Not built for `serve`'s chat path.**

- `ToolGateway` stamps each call with a per-session `LogicalClock`:
  `base_us + n * tick_us`, constant defaults (`0` and `1_000_000`), overridable
  as `clock_base_us` / `clock_tick_us` on `CausalMesh`, `from_config` and
  `ToolGateway`. That one value is the signed `timestamp_us`, the time the
  gate is asked about and the ledger row's `timestamp_us`, so a verdict, a
  ledger row and an event describe one moment and carry the same number.
- The wall-clock time of each call is kept in `ToolGateway.wall_times()`
  (event id to microseconds) and written to `run.json`'s unsigned
  `envelope.wall_time_us_by_event`, with the export time and the clock
  parameters. It never reaches the chain.
- Two sessions with the same seed and the same call sequence now have the
  same head hash (tested for the SDK, for the async path and for two
  `serve` apps driven over `/v1/tools/{name}/execute`). A different sequence
  gives a different head.
- A caller-supplied `now_us` is still signed as given, and the clock moves past
  it so later calls never go backwards behind it.
- Existing tests: none pinned the old wall-clock behaviour, so none changed.

**What it changes, stated rather than hidden.**

- **Time in a session is call count.** A lease or window of N seconds lasts N
  calls at the default tick, however long they take. That suits replay and
  is wrong for anything meant to measure real elapsed time. Nothing in the
  SDK measures real elapsed time today: the ledger's totals are over the run
  and ignore the timestamp (it is used for ordering), and the gate builds with
  `registry=None`, so SDK sessions hold no leases yet.
- **Leases must be granted on this clock.** `CausalMesh.now_us` is the moment
  to acquire at. A test wires a `ClaimRegistry` into a `ToolGateway` by hand
  and pins both halves: a lease granted at `now_us` blocks and then expires
  after the stated number of calls, and a lease granted on the wall clock is
  never seen to expire (the gate's clock never reaches it). Whoever adds
  claims to the SDK session must acquire at `now_us`, not `time.time()`. A
  lease is held on a resource identity (`path:src/a.py`), not the bare path.
- Timestamps are not dates. An auditor reading `timestamp_us: 0` must not read
  1970; the envelope's `clock.kind` says `logical`.
- The clock is thread-safe, but a timestamp is issued before the call runs, so
  concurrent callers can be signed out of chain order. The verifier checks no
  timestamp ordering, and `serve` serialises executions under a lock.

**What remains.**

- **`/v1/chat/completions` still signs the wall clock.** It does not go through
  `ToolGateway`: it calls `m._gate.policy.check` and `m._relay.ingest` itself
  with `time.time_ns()`, and puts that value in the event id too
  (`serve-<agent>-<now_us>-<n>`), so chat events in a `serve` chain are not
  reproducible. A test pins this so it stays visible. Fixing it means moving
  that path onto the gateway's clock (and a sequence-only event id); it was left
  alone here because `server/` is under separate edit.
- The harness (`tasks/runner.py`, the scheduler) has its own clock and was not
  touched.
