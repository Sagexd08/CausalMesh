# Claims ledger

Dated 2026-10-12. One row per claim this project, its README, its site or its
docs make or could be read as making. A claim is only as strong as the test
or file named in its evidence cell; a claim with no such cell is
`unverified`, not "probably fine".

**Statuses.**

- `verified`: a named test or file establishes it as worded, in the stated
  environment.
- `qualified`: true only with the stated limit. Say the limit whenever you
  say the claim.
- `unverified`: no evidence, or evidence that the opposite holds. Do not
  state it.
- `retired`: withdrawn. Do not state it until the recheck condition passes.

**How to read "verified date".** The evidence was read at the lines named on
that date. For a test, the full gate `python scripts/check.py` (Windows 11,
Python 3.13.5, PowerShell, 2026-10-12) reported ALL CHECKS PASSED with 2918
passed, 15 skipped and 0 failed in 16m26s; the names of the 15 skipped tests
are not in the report this ledger was written from, so a row whose test is
among them is UNKNOWN until checked. Only
`tests/integration/test_adoption_hook.py` was re-run individually for this
ledger. Everything ran a deterministic mock agent or synthesized input, on
Windows only.

| Claim | Status | Evidence (file:line / test) | Verified | Recheck |
|---|---|---|---|---|
| A run's events form a signed hash chain that `causalmesh verify` checks offline | verified | `tests/adversarial/test_attack_battery.py:45` (`test_clean_chain_is_valid`); `tests/integration/test_cleanroom_verification.py:133` (verifier in a separate subprocess and working directory, reading only exported files) | 2026-10-12 | Any change under `src/causalmesh/crypto/` or `verifier/` |
| `verify` proves the named actor signed the events | qualified | Only against an operator-supplied ring: `tests/adversarial/test_verify_keyring.py:63` shows a chain re-signed under an attacker key passes without `--keyring` and fails with it; `docs/backlog.md:1343` records the limit | 2026-10-12 | When `key_ring_fingerprint` is pinned automatically (not built) |
| Any change, insertion, deletion, reordering or reassignment of recorded events is detected | verified | `tests/adversarial/test_attack_battery.py`: `TestMutation` (L64), `TestInsertion` (L129), `TestDeletion` (L181), `TestReordering` (L208), `TestAttribution` (L231); on-disk tamper in `tests/integration/test_cleanroom_verification.py:164` | 2026-10-12 | Any change to the chain format or verifier |
| Truncating the end of a chain is detected | qualified | Undetected without an external anchor: `tests/adversarial/test_attack_battery.py:288`; detected with one: `:307`. `README.md` (Status, "Suffix truncation") says the same | 2026-10-12 | When anchoring is on by default (not built) |
| Write leases are exclusive: at most one valid holder per path, same machine | verified | `src/causalmesh/claims/registry.py:325-418` (`BEGIN IMMEDIATE`); threads `tests/property/test_claim_exclusivity.py:57`; processes `:117-188`; generated schedules `:216` | 2026-10-12 | Any change to `claims/registry.py`; and on Linux and macOS (see below) |
| A second agent is refused before it writes, and the file is byte-identical, when the gate is given a registry | verified | `tests/integration/test_claim_enforcement.py:63-82`; gate-level `tests/unit/test_policy.py:419-455` (`TestClaims`); rule at `src/causalmesh/policy/gate.py:373-397`. The integration test calls `ClaimRegistry.may_write` directly, not `Gate` | 2026-10-12 | Any change to `gate.py` or `registry.py` |
| An SDK session given `claims=` refuses a second agent | qualified | `src/causalmesh/sdk/mesh.py:770` passes the registry through only when the caller supplies one ("None unless the caller opted in"); `tests/sdk/test_claims.py:105-122` (`TestTwoAgentsContendingForOnePath`; off by default at `:77`). A session built without `claims=` has no lease enforcement | 2026-10-12 | If `claims=` becomes the default |
| The example Claude Code hook denies a `Write` or `Edit` on a path another role owns | qualified | Ownership only. `tests/integration/test_adoption_hook.py:75-83` (synthesized JSON, real bash subprocess; the reason is asserted to name the path and the owner as of this ledger). Never run by a real `claude` session | 2026-10-12 | After backlog (g) is done |
| **"Prevents conflicting writes between Claude Code agents"** | **retired** | Against: the hook's gate has no registry (`src/causalmesh/cli/commands_policy.py:179`), so the claim rule returns `None` (`src/causalmesh/policy/gate.py:381-382`); the hook gives every session one identity (`docs/examples/claude-pretooluse.sh:28`) | 2026-10-12 | Retired until a subprocess test passes in which agent A's lease makes the hook deny agent B with a reason naming A, and a recorded two-session `claude` run exists (`docs/backlog.md`, entries (a), (g), (j)) |
| The hook gates all of an agent's writes | retired | It matches `Write\|Edit` only; `MultiEdit`, `NotebookEdit` and `Bash` are allowed without a check (`docs/examples/claude-pretooluse.sh:19-22`) | 2026-10-12 | `docs/backlog.md` entry (b) |
| The hook fails closed when its inputs are bad | unverified | Observed 2026-10-12: bad JSON gives exit 5 and `jq` missing gives exit 127, both with no output; a missing CLI or contract gives a deny with an empty reason. What Claude Code does with exit 5 or 127 is UNKNOWN. No test | 2026-10-12 | `docs/backlog.md` entry (h) |
| Leases are fenced / safe under lease expiry | unverified | No fencing token exists in `src/` or `docs/` outside the audit and backlog. Expiry is lazy (`src/causalmesh/claims/registry.py:303`) | 2026-10-12 | `docs/backlog.md` entry (c) |
| Leases are renewed automatically | unverified | `renewal_interval_seconds` appears only in `docs/claims.md`; no code in `src/` reads it or calls `ClaimRegistry.renew` | 2026-10-12 | `docs/backlog.md` entry (d) |
| Coordination across devices or machines | unverified | Not built. `docs/claims.md` ("What this does not do"): SQLite serializes within one filesystem. `causalmesh serve` builds no `ClaimRegistry`. Behaviour on a network filesystem is UNKNOWN | 2026-10-12 | `docs/backlog.md` entry (i) |
| The chain is bit-reproducible | qualified | Same seed gives the same chain: `tests/reproducibility/test_chain_determinism.py:71`, `:207`; `tests/reproducibility/test_collection_determinism.py:111`. Limits: one intermittent failure of the last test is unexplained (`docs/backlog.md:1381`); the chat path signed wall-clock time until the 2026-10-12 fix (`docs/backlog.md:1031`); a run with a hosted model is not reproducible (`docs/adapters.md:247`, `README.md:385`) | 2026-10-12 | If the intermittent failure recurs, or is root-caused |
| The full local gate is green | verified | `python scripts/check.py`: ALL CHECKS PASSED, 2918 passed, 15 skipped, 0 failed, 16m26s, Windows 11, Python 3.13.5, run from PowerShell, 2026-10-12. 13 earlier failures in that environment were environment-dependent and fixed (`docs/backlog.md:1398`) | 2026-10-12 | Before every merge; the result is for one machine and one day |
| Works on Linux and macOS | unverified | Never run there. `AGENTS.md` ("Commands"): each OS needs a run of its own; `docs/launch-checklist.md:74` | 2026-10-12 | One gate run per OS with the log kept |
| CI-tested | retired | No CI: the workflow was removed (`docs/backlog.md:1045`); `AGENTS.md` says "There is no CI" | 2026-10-12 | If a test workflow runs again and passes |
| Any statement about how real LLM agents behave under these controls | unverified | Every run used a deterministic mock agent (`AGENTS.md`, "What not to do"; `README.md` Status) | 2026-10-12 | After a run with a real hosted model, recorded under `docs/evidence/` |

## Changing this file

Move a row only with the file or test that changes it, named in the same
change. A `verified` row whose evidence is deleted or whose test starts
skipping goes back to `unverified` until someone looks. A claim that appears
in `README.md`, the site or a release note and is missing from this table is
unverified.
