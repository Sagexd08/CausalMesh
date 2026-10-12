# CausalMesh Ship Audit (Phase 0 ground truth)

Date: 2026-10-12. Scope: PRD v3.0 (Rust+Tauri desktop atlas, engineering memory, health,
cross-device coordinator, MCP, TUI) compared with the repository at `19d6507` plus the
uncommitted working tree. Method: four read-only scans (capabilities, hook and claim
enforcement, skill supply chain, toolchain and names), then this synthesis. Nothing in
the audit installed software or changed product code.

## 1. Verdict

1. What exists is a Python enforcement-and-evidence substrate: a signed Ed25519 hash chain,
   a policy gate and single-filesystem SQLite write leases. It is about 31.7k lines of src and
   35.6k lines of tests, at 0.1.0 pre-alpha.
2. None of the PRD's headline product exists: no code graph, no memory, no health score, no
   MCP, no desktop app and no coordinator.
3. The one enforcement path a user would actually adopt (the Claude Code hook) never consults
   claims, so "prevents conflicting writes" is not true end to end.
4. 0.1.0 is not releasable yet. The gate is not green, history is not rewritten, CI is
   absent and Linux/macOS have never been run.
5. Ship what exists honestly first. Do not start Rust or Tauri now.

## 2. PRD capability vs reality

| # | PRD capability | Status | Biggest gap |
|---|---|---|---|
| 1 | Code atlas (graph) | ABSENT | No ast/tree-sitter/networkx in src. `edges/` is an event graph over the chain, and CAUSED/RECOVERED/SUPERSEDED have no writer |
| 2 | Engineering memory | ABSENT | No FTS. `storage/index.py` is a run-state index |
| 3 | Code health | ABSENT | `metrics/accounting.py` measures coordination cost, not code |
| 4 | Cross-device coordinator | ABSENT | docs/claims.md:142-143: "No cross-machine coordination. SQLite serializes within one filesystem." `serve` (server/app.py) is a gate-and-record LLM proxy, not a claim coordinator |
| 5 | MCP server | ABSENT | Zero MCP code |
| 6 | Desktop app (Tauri) | ABSENT | No Cargo.toml or tauri.conf.json outside worktrees |
| 7 | TUI | PARTIAL | `rich` only. tui/monitor.py is a read-only live view with no interaction |
| 8 | Write-conflict prevention | PARTIAL | Leases are exclusive (claims/registry.py:325-418) but have no fencing, no heartbeat and no atomic multi-acquire, and the hook ignores them (cli/commands_policy.py:179) |
| 9 | Signed audit / verify | PRESENT | Verified on Windows only. Linux/macOS are UNKNOWN |

## 3. What the repo proves about conflicting writes

**Proven:**

- **Same-machine exclusivity.** Acquire is exclusive under SQLite `BEGIN IMMEDIATE`
  (claims/registry.py:325-418), with renew at L420, release at L471, `may_write` at L508 and
  `record_denial` at L538.
- **In-process denial.** A second actor is denied before writing
  (tests/integration/test_claim_enforcement.py:62-82).
- **Cross-process exclusivity.** Acquire stays exclusive when callers race from separate
  processes (tests/property/test_claim_exclusivity.py:121-188).
- **C2 collision.** The C2 arm allows the collision, but this is shown by in-process
  simulation (test_claim_enforcement.py:126-162), not through the hook.

**Not proven, or false:**

- **The hook does not enforce claims.** `causalmesh policy check --stdin` builds
  `Gate(contract, run_id="policy-check", enforcing=...)` with no claim registry
  (cli/commands_policy.py:179). The claim rule (policy/gate.py:373-397) is therefore inert,
  and the hook denies on ownership only, never on another agent's active claim.
- **The hook covers only some tools.** docs/examples/claude-pretooluse.sh matches
  `Write|Edit`. MultiEdit, NotebookEdit and Bash are never gated.
- **No real-session evidence.** tests/integration/test_adoption_hook.py feeds synthesized
  JSON to bash and never runs a real `claude` session. Its deny-reason assertion is vacuous
  (L79-81).
- **Fail-closed behaviour is unknown.** It is UNKNOWN whether the hook fails closed when
  `jq` is missing under `set -euo pipefail`. It depends on how Claude Code treats that exit,
  which nobody has verified.
- **The runner discards refusals.** The runner calls `claims.acquire` per path and throws
  away the `ClaimOutcome` (tasks/runner.py:351-360), so a refused lease still proceeds.
- **The claim rule never fires on runner leases.** Runner leases use raw paths (open item,
  docs/backlog.md:1363-1365).
- **No stale-holder protection.** Expiry is lazy (registry.py:303) and there are no fencing
  tokens anywhere in src or docs.
- **No heartbeat.** docs/claims.md:127-133 documents `renewal_interval_seconds: 30`, but
  nothing in src reads it or calls `.renew`.
- **Handoff is not atomic.** It is a release followed by an acquire.
- **Undocumented gaps.** Fencing, heartbeat and atomic acquire were missing from
  docs/backlog.md. That breaks the repo's own rule (AGENTS.md, "Record what is not built").
- **Stale doc.** docs/claims.md still says tool-layer integration "arrives in Step 6".
- **No agent-behaviour evidence.** Every run used a deterministic mock agent (AGENTS.md).

## 4. Risks, ranked

1. **Claims honesty (severity high).** The marketing-level claim "prevents conflicting
   writes" is backed only in-process, while the adoption path ignores claims (Section 3). If
   this ships as written, the first user with two Claude sessions on one file disproves it.
2. **Security of the enforcement path.** The hook covers two of the write-capable tools
   (Write, Edit; not MultiEdit, NotebookEdit or Bash). Its fail mode with missing `jq` is
   unverified.
3. **Naming collision.** There are 9 GitHub repos named causalmesh. VictorAgahi/causalmesh
   (10 stars, Apache-2.0) is "MCP server that gives your AI coding agent a map of your
   polyglot codebase", which is exactly the PRD's atlas+MCP positioning.
   ateeqdesktop-dot/causalmesh (MIT) does causal failure attribution for agent traces.
   Building the atlas under this name walks straight into that collision.
4. **Release readiness.**
   - The first full gate run this session was 19 failed / 2888 passed.
   - 9 of those failures reproduced in isolation; all are fixed in the working tree (two
     causes: a stale editable install path and Windows path/`bash` resolution).
   - 10 failures passed in isolation but failed in the full run: adoption_hook x3,
     cooperbench hidden x3, welcome palette x4. The cause is unexplained and may depend on
     test order or load. A clean re-run was started afterwards; its result is recorded in
     the launch checklist, not here.
   - Linux/macOS have never been run, CI is absent and Actions are disabled by billing.
5. **Determinism claim.** One intermittent determinism-test failure is unexplained
   (docs/backlog.md), and the chat path signed wall-clock time until the 2026-10-12 fix in
   the working tree. "Bit-reproducible" must be stated with that qualification until the
   intermittent failure is root-caused.
6. **Supply chain and repo hygiene.**
   - Installed typer is 0.15.2 against a declared `typer>=0.16`, so the suite has never run
     on the declared floor.
   - History contains hostname and username in 3 commits, and videos/.claude/.impeccable are
     tracked.
   - hairline-create is vendored (docs/skills-inventory.md) but its `look.mjs` is not run
     because it runs `npm install playwright-core@1`.
   - The `npx skills` installer was not reviewed and not used.
   - .github/workflows/publish.yml was switched on 2026-10-12 from a token upload to PyPI
     trusted publishing (`environment: pypi`, `id-token: write`); it cannot run until
     Actions billing is restored.
   - Name availability: free on PyPI and npm, inconclusive on crates.io.

## 5. Stack decision

**Recommendation: no Rust rewrite and no Tauri desktop now.** Every blocking gap is a
correctness or honesty gap in existing Python (hook wiring, refusal handling, fencing), not a
language limit. A rewrite would discard 35.6k lines of tests that are the project's only
evidence. A desktop atlas has nothing to render, because no code graph exists (Section 2,
row 1).

The toolchain is ready if needed: Rust 1.95.0, MSVC 14.43, WebView2 155, tauri 2.12.3,
ratatui 0.30.2, tree-sitter 0.27.1, rusqlite 0.40.2, tokio 1.53.2 and rmcp 3.5.1, all
MIT/Apache-compatible. Readiness is not justification.

**Conditions that would change this:**

- **Hook latency.** Python startup per PreToolUse call is UNKNOWN. Measure it. If p95 exceeds
  the latency budget the owner sets, a small Rust hook/coordinator binary (not a rewrite)
  becomes justified.
- **Validated demand for the desktop.** If the Python code graph (C3) exists and users ask
  for a visual surface, then Tauri is justified for the desktop shell only, over the
  existing core.

## 6. Revised phases

### Track A: ship 0.1.0 of what exists (no new capabilities)

**A1. Green gate.**
- Commit the working tree.
- Exit: `python scripts/check.py` passes twice consecutively on Windows from a fresh venv
  with a non-editable install.
- Exit: the 10 order-dependent failures are root-caused or recorded in backlog.
- Exit: the suite passes with `typer==0.16.0` pinned, or the floor is lowered to match what
  was tested.

**A2. Honest docs.**
- docs/backlog.md gains entries for fencing tokens, heartbeat, atomic multi-acquire, the
  hook ignoring claims, ungated MultiEdit/NotebookEdit/Bash, and the runner discarding
  `ClaimOutcome`.
- docs/claims.md loses "arrives in Step 6".
- Exit: `grep` finds each item in backlog. README makes no claim from the "not allowed"
  list (Section 7).

**A3. Hygiene.**
- Rewrite history with filter-repo, keeping all commits.
- Exit: `git log -p --all` has zero hits for the hostname and username, and
  videos/.claude/.impeccable are absent from all commits.

**A4. Platforms.**
- Exit: the gate passes on one Linux and one macOS machine, with the logs kept.

**A5. Publish.**
- Exit: `pip install causalmesh==0.1.0` in a clean venv, then `causalmesh doctor` and
  `causalmesh verify` on a demo run succeed.
- Two PyPI owners are set. This step is gated on the naming decision (Section 8).

### Track B: make the core claim true (still Python)

**B1. Claims in the hook path.**
- `policy check` builds `Gate` with the claim registry.
- The hook matches `Write|Edit|MultiEdit|NotebookEdit` and fails closed when `jq` is absent.
- Exit: a subprocess test where agent A holds a claim and agent B's hook call returns
  `deny`, with an asserted non-vacuous reason that names A's claim.
- Exit: one recorded manual run with two real `claude` sessions.

**B2. Refusal honoured.**
- The runner stops or skips on `granted == False`, and leases use normalized resource ids
  (backlog:1363-1365).
- Exit: a test where a refused acquire leads to no write and a recorded denial.

**B3. Lease safety.**
- Add fencing tokens (monotonic per resource, checked at write), plus heartbeat renewal that
  reads `renewal_interval_seconds`.
- Exit: a property test where an expired holder's write is rejected by token.
- Exit: a mutation check showing that removing the token check fails that test.

### Track C: new product capabilities (each gated on Track B done)

**C1. MCP server.**
- Exposes the existing claims, `may_write` and `verify` as an optional extra (not a runtime
  dependency).
- Exit: an MCP client acquires a claim, and a second client is refused.

**C2. Cross-device coordinator.**
- Networked claim service with fencing.
- Exit: a two-machine test where a partitioned stale holder is rejected.

**C3. Code graph, then memory, then health.**
- Built in Python, in that order. Each needs a written user need before starting.
- Exit per item: a fixture repo produces a graph, search results or scores that are asserted
  in tests.

**C4. Desktop/Rust.**
- Only if a Section 5 condition is met.

## 7. Claims

**Allowed today:**

- Runs produce an Ed25519-signed hash chain that `causalmesh verify` checks offline. It is
  reproducible in the tested configuration; one intermittent determinism-test failure is
  unexplained and tracked.
- Within one filesystem, write leases are exclusive across processes
  (test_claim_exclusivity.py:121-188).
- In the library and gate, a second agent is refused before writing
  (test_claim_enforcement.py:62-82).
- An example Claude Code hook denies Write/Edit outside an agent's declared ownership.
- Tested on Windows only. Pre-alpha.

**Not allowed:**

- "Prevents conflicting writes between Claude Code agents." The hook ignores claims.
- Anything cross-machine, cross-device or distributed.
- "Safe under lease expiry" or "fenced".
- "Gates all agent writes." Bash, MultiEdit and NotebookEdit are ungated.
- MCP, code atlas or graph, engineering memory, code health, or desktop app.
- Linux/macOS support, or "CI-tested".
- Any statement about real agent behaviour (mock agent only).
- Unqualified "bit-reproducible".

## 8. Decisions only the owner can make

1. **Name.** Keep "causalmesh" given VictorAgahi/causalmesh's MCP-atlas positioning, or
   rename before PyPI publish and before any atlas or MCP work.
2. **Scope.** Is the product the enforcement substrate (Tracks A-B, consistent with "lead
   with the gate" and "Rails for agents"), or the PRD's atlas/memory/health desktop? These
   are different products. Committing to Track C3/C4 is a pivot.
3. **Release honesty bar.** Whether 0.1.0 may ship before B1, with the hook documented as
   ownership-only, or must wait for B1.
4. **Hook latency budget**, which feeds the Section 5 Rust condition.
5. **CI funding.** Re-enable Actions billing, or accept a manual multi-OS gate.
6. **Order-dependent failures.** Whether the 10 unexplained full-run failures block 0.1.0 or
   ship as recorded backlog items.
