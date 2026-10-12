# Ship log, phase A: 2026-10-12

A dated record of one day's work on getting 0.1.0 honest. Each statement says
where it came from: **read** means the author of this entry read it in the
repository on 2026-10-12; **reported** means it came from the owner's or the
session's account of work done outside what this entry could re-check, and is
not re-verified here. Anything neither is marked UNKNOWN.

## What was audited

- **A read-only audit** of the repository against the PRD, written up in
  `docs/SHIP-AUDIT.md` (read). Its four scans were capabilities, hook and
  claim enforcement, skill supply chain, and toolchain and names. Its
  verdict: the repository is an enforcement-and-evidence substrate; the
  Claude Code hook never consults claims, so "prevents conflicting writes"
  is not true end to end; 0.1.0 was not releasable on the audit's date.
- **A docs and claims pass** on the same day, the subject of this entry.
  Each claim about claim enforcement was re-read at the cited lines before
  it was written down. The result is in these files:
  `docs/backlog.md` (section "Claim enforcement: what the audit of
  2026-10-12 found missing", entries (a) to (j)), `docs/claims.md`,
  `docs/adoption.md`, `README.md` (Status), `docs/claims-ledger.md` (new),
  and two test files.
- **Two things were observed by running the hook**, which the audit had
  listed as unknown: with bad JSON on stdin it exits 5, with `jq` off `PATH`
  it exits 127, in both cases with nothing on stdout; with no `causalmesh`
  or no contract it prints a `deny` with an empty reason and exits 0. How
  Claude Code treats exit 5 or 127 remains UNKNOWN. Method and caveats are
  in `docs/backlog.md`, entry (h).

## The gate

| Item | Value |
|---|---|
| Command | `python scripts/check.py` |
| Result | ALL CHECKS PASSED (reported) |
| Suite | 2918 passed, 15 skipped, 0 failed (reported) |
| Duration | 16m26s (reported) |
| Environment | Windows 11, Python 3.13.5, run from PowerShell (reported) |
| Scope | One machine, one day. Linux and macOS have not been run. There is no CI. |

Which 15 tests were skipped is UNKNOWN to this entry. The 2026-09-30 count in
the README's Status paragraph (1710 passed, 41 skipped, Python 3.12) is an
older measurement and was left as written because it is dated.

## The 13 environment-dependent failures

Recorded in full in `docs/backlog.md` ("Thirteen tests 'failed only in the
full run': it was the invoking shell, not test order", read). In short:

- **What failed.** 13 tests passed under Git Bash and failed standalone under
  the PowerShell tool's environment: `test_adoption_hook::TestClaudeCodeHookAdapter`
  x3, `test_cli::TestModuleEntryPoint`, `test_cooperbench_batch_run::TestThreeWayMerge`
  x2, `test_cooperbench_hidden_tests` x3, `test_welcome::TestPalette` x3 and
  `TestOnboardUsesTheSharedPalette` x1.
- **Cause.** Not test order. In that environment `NO_COLOR=1` and
  `PYTHONIOENCODING=utf-8:surrogateescape` are set, and `PATH` carries
  Git's `cmd` directory but not its `bin`, so a bare `bash` resolves to the
  WSL launcher at System32, which exits 1 with no distro installed.
- **Fix** (commit `9aca66d`, read from the log and the backlog entry): the
  palette test pins `no_color=False`; the module-entry-point test sets the
  child's encoding and decodes as UTF-8; `tasks.runner.resolve_executable`
  probes `bash -c "exit 0"` and falls back to the Git for Windows `bash`
  beside `git`, pinned by `tests/unit/test_resolve_executable.py`.
- **Relation to the audit's count.** `docs/SHIP-AUDIT.md` (section 4, item 4)
  reports 19 failed in its first run and lists 10 as unexplained (adoption
  hook x3, cooperbench hidden x3, welcome palette x4). Those 10 are inside
  the 13 above by name and are now explained. How the other 3 map onto the
  audit's 9 reproducible failures is UNKNOWN. The audit text was not
  updated.
- **Still open.** `tests/unit/test_x402_pay.py::TestBudgetInterplay::test_concurrent_payments_cannot_overspend_together`
  paid 3 of an expected 4 once under load and passed 6 of 6 alone; not
  explained. `scripts/check.py` does not pin `NO_COLOR` or
  `PYTHONIOENCODING`.

## The history rewrite (reported)

- **What.** The repository history was rewritten: 8 media files were
  stripped from history, and one identifier was redacted in 4 manifest
  commits. All commit counts were preserved. The audit's A3 step planned
  `git filter-repo`; which tool was used is UNKNOWN to this entry.
- **Backup.** `C:\Desktop\causalmesh-prerewrite-2026-10-12.bundle` exists
  (read: 190,763,735 bytes, and `git bundle list-heads` lists refs from it).
  Whether it is a complete pre-rewrite copy of every ref is UNKNOWN to this
  entry.
- **Not re-verified here.** The file list, the identifier and the commit
  counts were not re-checked by this entry. The check the audit set for it
  (`git log -p --all` returns zero hits for the hostname and username, and
  the stripped paths are absent from all commits) has not been re-run by
  this entry. The working copy's `git rev-list --count --all` is 538 and
  `git log --oneline` on `main` is 272; those numbers are stated for
  reference, not as a preserved-count check.

## The incident (reported)

After the rewrite, a pull re-merged the old, pre-rewrite history into `main`
on GitHub. It was repaired by rewriting `main` again. The local checkout this
entry was written from sits at `9aca66d` on `main` with a clean tree. What the
remote `main` points at now was not queried by this entry and is UNKNOWN. A
clone made before the rewrite still holds the old history, and pulling from
it into `main` can bring that history back, so such clones are better
replaced than pulled.

## Decisions only the owner can make

1. **Name.** `VictorAgahi/causalmesh` describes itself as an MCP server that
   gives an AI coding agent a map of a polyglot codebase
   (`docs/SHIP-AUDIT.md`, section 4, item 3, read). Keep the name,
   or rename before any PyPI publish.
2. **Release bar.** Whether 0.1.0 may ship with the hook documented as
   ownership-only (the state after this pass), or must wait for the claims
   to be wired into the hook (backlog (a), (g), (j)).
3. **CI funding.** Re-enable Actions billing, or accept a manual per-OS gate
   (`docs/backlog.md`, "CI was removed").
4. **Personal-email scrub.** Whether and where the owner's personal email
   address is to be removed. This entry did not search the history or the
   tree for it; its extent is UNKNOWN.
5. **Remote branch cleanup.** 20 remote branches remain (reported; the local
   remote-tracking refs also show 20 plus the `origin/HEAD` pointer, not
   re-fetched). Which to keep or delete is the owner's call; none was touched.
6. **Order-dependent failures.** The audit asked whether the unexplained
   full-run failures block 0.1.0. The 13 are now explained; the x402
   failure above is not.

## Not done in this phase

- No push, no remote or branch change, no commit by the author of this
  entry.
- No fencing, heartbeat, atomic acquire, hook change or runner change. They
  are recorded, not built.
- The full suite was not re-run after the docs and test edits; only
  `tests/integration/test_adoption_hook.py` and
  `tests/integration/test_claim_enforcement.py` were (11 passed), with
  `ruff check` and `ruff format --check` clean on both files.
- Linux and macOS: not run.
