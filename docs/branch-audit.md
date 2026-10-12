# Branch audit

Date: 2026-10-13. Base: `origin/main` @ `03f3b74` (tag `v0.1.0`, annotated tag object `0444ec4`, points at `03f3b74`).
Scope: the 19 non-main `origin/*` branches and the 17 local branches that have no live upstream (16 with none configured, plus `ship/mesh-sdk` whose upstream is gone).

## 1. What this document is not

- No ref was changed by this audit. None of its commands fetches, prunes, merges, deletes, moves or checks out; all are read-only. The remote-tracking refs reflect the last fetch, not a live view of the remote.
- It records no decision about branch disposition. None was found: `docs/ship-log/PHASE-A.md:118-120` says "Which to keep or delete is the owner's call; none was touched."
- It is not a recommendation to delete anything. The `classification` column describes what the matching methods found, not what should happen.
- It does not claim that two commits are equivalent in intent. Patch-id and subject matching are heuristics (section 4).

Note on the base: the local `main` branch is at `b4454fe` (2026-10-13 01:30 +0530), one commit ahead of `origin/main` and not pushed. This audit uses `origin/main` throughout, as asked, so `b4454fe` is outside every count below.

### How to reproduce

```bash
git for-each-ref --format='%(refname)|%(upstream)|%(upstream:track)' refs/heads refs/remotes
git worktree list --porcelain
git rev-list --left-right --count origin/main...<ref>        # behind, ahead
git merge-base origin/main <ref>; git rev-list --count <merge-base>
git rev-list --count --merges origin/main..<ref>             # merges (git cherry skips them)
git cherry origin/main <ref>                                  # '+' patch-id not on main, '-' equivalent on main
git log origin/main --format='%s%x09%an'                      # subject + author name pairs on main
git log -1 --format='%s%x09%an%x09%ci' <sha>                  # for each '+' commit
git show --name-only --format= <sha>                          # file set, compared with the main counterpart
git rev-parse --verify origin/main:<path>                     # blob at main tip vs blob in <sha>
git log origin/main..<ref> --format='%H %ae %ce' | grep -c -E 'gmail\.com|snuindia\.in'   # commits, not lines
```

Columns in the tables below:

- `ahead/behind` is `origin/main..ref` / `ref..origin/main`. Every ref is behind by 230.
- `+/-` is the `git cherry` split of the non-merge commits; `ahead = + + - + merges` holds for every row.
- `(b)` is the number of `+` commits with no commit on `origin/main` that has the same subject and the same author name.
- `(c)` is the number of `+` commits whose subject and author name do match a main commit but whose file set does not (overlap below 0.9). They are not counted as copies. This column is an addition to the requested method; see section 4.
- `addr` is the number of commits in `origin/main..ref` whose author or committer address is at gmail.com or snuindia.in (a commit count; no address is printed here).
- Tip date is the committer date (`+0530`). All 36 refs share the merge-base `48fcdfa` (2026-09-15, 44 commits in its history: the early commits whose hashes survived the rewrite).

## 2. Remote branches (19)

| branch | tip | tip date | tip author | ahead/behind | +/- | merges | (b) | (c) | addr | classification | action |
|---|---|---|---|---|---|---|---|---|---|---|---|
| origin/dev | 74ecbfc | 2026-09-30 16:56 | Rohit Kumar Kundu | 218/230 | 12/177 | 29 | 1 | 0 | 185 | has unique work | none taken; owner decision required before any delete |
| origin/feat/adapters | f3bc853 | 2026-09-30 15:19 | ROHIT8759 | 154/230 | 10/135 | 9 | 0 | 0 | 151 | superseded | none taken; owner decision required before any delete |
| origin/feat/causalmesh-film | 11e6606 | 2026-09-30 14:07 | Sagexd08 | 149/230 | 10/130 | 9 | 0 | 0 | 146 | superseded | none taken; owner decision required before any delete |
| origin/feat/cooperbench | 5868d18 | 2026-09-30 15:21 | ROHIT8759 | 154/230 | 10/135 | 9 | 0 | 0 | 151 | superseded | none taken; owner decision required before any delete |
| origin/feat/evidence | cd122be | 2026-09-30 15:44 | ROHIT8759 | 154/230 | 10/135 | 9 | 0 | 0 | 151 | superseded | none taken; owner decision required before any delete |
| origin/feat/packaging | b1f0f43 | 2026-09-30 15:44 | ROHIT8759 | 154/230 | 10/135 | 9 | 0 | 0 | 151 | superseded | none taken; owner decision required before any delete |
| origin/feat/policy-plane | 18bad1d | 2026-09-15 13:14 | Sagexd08 | 8/230 | 3/5 | 0 | 0 | 0 | 8 | superseded | none taken; owner decision required before any delete |
| origin/feat/scaling | 58b6d98 | 2026-09-30 15:22 | ROHIT8759 | 156/230 | 10/137 | 9 | 0 | 0 | 153 | superseded | none taken; owner decision required before any delete |
| origin/feat/scheduler | 4ac55dc | 2026-09-30 15:44 | ROHIT8759 | 152/230 | 11/132 | 9 | 0 | 1 | 149 | needs owner review | none taken; owner decision required before any delete |
| origin/feat/server | 923c9d4 | 2026-09-30 15:44 | ROHIT8759 | 153/230 | 10/134 | 9 | 0 | 0 | 150 | superseded | none taken; owner decision required before any delete |
| origin/feat/tasks | e13e01c | 2026-09-30 15:17 | ROHIT8759 | 154/230 | 10/135 | 9 | 0 | 0 | 151 | superseded | none taken; owner decision required before any delete |
| origin/feat/website | feb891e | 2026-09-30 14:47 | ROHIT8759 | 151/230 | 10/132 | 9 | 0 | 0 | 148 | superseded | none taken; owner decision required before any delete |
| origin/feat/x402 | a9d1141 | 2026-09-30 15:16 | ROHIT8759 | 154/230 | 10/135 | 9 | 0 | 0 | 151 | superseded | none taken; owner decision required before any delete |
| origin/feature/phase1-sdk-gateway | 4d6d2bc | 2026-09-28 16:09 | ROHIT8759 | 87/230 | 3/82 | 2 | 0 | 0 | 87 | superseded | none taken; owner decision required before any delete |
| origin/feature/phase2b-framework-adapters | 7b9a58a | 2026-09-28 20:22 | ROHIT8759 | 99/230 | 4/92 | 3 | 0 | 0 | 98 | superseded | none taken; owner decision required before any delete |
| origin/feature/phase2b-openai-adapter | 0ed11e5 | 2026-09-28 21:01 | ROHIT8759 | 103/230 | 4/96 | 3 | 0 | 0 | 102 | superseded | none taken; owner decision required before any delete |
| origin/fix/sdk-evidence-gaps | 61611df | 2026-09-28 05:01 | Sagexd08 | 86/230 | 4/80 | 2 | 0 | 0 | 86 | superseded | none taken; owner decision required before any delete |
| origin/fix/test-quickstart-wrapping | 969dc9a | 2026-09-30 01:15 | ROHIT8759 | 131/230 | 5/118 | 8 | 0 | 0 | 130 | superseded | none taken; owner decision required before any delete |
| origin/fix/test-serve-dependencies | 604953e | 2026-09-28 21:06 | ROHIT8759 | 103/230 | 4/96 | 3 | 0 | 0 | 102 | superseded | none taken; owner decision required before any delete |

Totals: 17 superseded, 1 has unique work, 1 needs owner review. `superseded` means nothing unique was found by patch-id, subject or file set; it does not mean the branch is safe to remove.

Notes:

- `origin/feature/phase2b-openai-adapter` (`0ed11e5`) and `origin/fix/test-serve-dependencies` (`604953e`) are different commits with an identical tree (`git diff` is empty); neither is an ancestor of the other.
- The local branches `feat/causalmesh-film`, `feat/policy-plane` and `fix/sdk-evidence-gaps` track their `origin/*` namesakes at the same tip, so they add nothing to the table.

## 3. Local-only branches and worktrees (17)

| branch | tip | tip date | tip author | ahead/behind | +/- | merges | (b) | (c) | addr | classification | worktree | action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ship/claim-backtracking | 9054bd4 | 2026-09-29 14:09 | Sohom Chatterjee | 108/230 | 4/100 | 4 | 0 | 0 | 107 | superseded | .worktrees/claim-backtracking | none taken; owner decision required before any delete |
| ship/cooperbench-import | 3f1db89 | 2026-09-29 22:38 | Sagexd08 | 83/230 | 3/78 | 2 | 0 | 0 | 83 | superseded | .worktrees/cooperbench-import | none taken; owner decision required before any delete |
| ship/edges-cli | f37feb9 | 2026-09-28 14:38 | Sagexd08 | 88/230 | 6/80 | 2 | 2 | 0 | 88 | has unique work | .worktrees/edges-cli | none taken; owner decision required before any delete |
| ship/integrate | 033aafb | 2026-09-28 14:38 | Sagexd08 | 102/230 | 17/80 | 5 | 13 | 0 | 102 | has unique work | .worktrees/integrate | none taken; owner decision required before any delete |
| ship/kappa-coding | 265f770 | 2026-09-29 14:21 | Sagexd08 | 86/230 | 3/81 | 2 | 0 | 0 | 86 | superseded | .worktrees/kappa-coding | none taken; owner decision required before any delete |
| ship/real-agent-hardening | 9054bd4 | 2026-09-29 14:09 | Sohom Chatterjee | 108/230 | 4/100 | 4 | 0 | 0 | 107 | superseded | .worktrees/real-agent-hardening | none taken; owner decision required before any delete |
| ship/scaling-profile | 24ddea8 | 2026-09-28 00:05 | ROHIT8759 | 82/230 | 3/77 | 2 | 0 | 0 | 82 | superseded | .worktrees/scaling-profile | none taken; owner decision required before any delete |
| ship/sdk-completion | cb4168f | 2026-09-28 14:22 | Sagexd08 | 91/230 | 9/80 | 2 | 5 | 0 | 91 | has unique work | .worktrees/sdk-completion | none taken; owner decision required before any delete |
| ship/task-families | 7ecffdc | 2026-09-28 14:25 | Sagexd08 | 91/230 | 9/80 | 2 | 5 | 0 | 91 | has unique work | .worktrees/task-families | none taken; owner decision required before any delete |
| ship/tui-polish | 3bf615a | 2026-09-29 14:33 | Sagexd08 | 84/230 | 3/79 | 2 | 0 | 0 | 84 | superseded | .worktrees/tui-polish | none taken; owner decision required before any delete |
| ship/ui | 5059c0b | 2026-09-29 14:45 | Sagexd08 | 101/230 | 17/80 | 4 | 13 | 0 | 101 | has unique work | .worktrees/ui | none taken; owner decision required before any delete |
| ship/video | 7e2fb33 | 2026-09-29 14:36 | Sagexd08 | 89/230 | 5/82 | 2 | 0 | 0 | 89 | superseded | .worktrees/video | none taken; owner decision required before any delete |
| ship/whitepaper | f707f37 | 2026-09-28 14:28 | Sagexd08 | 99/230 | 15/80 | 4 | 11 | 0 | 99 | has unique work | .worktrees/whitepaper | none taken; owner decision required before any delete |
| worktree-agent-a0862468b9dbe0fe3 | 19d6507 | 2026-10-04 01:35 | Sohom Chatterjee | 224/230 | 11/183 | 30 | 0 | 0 | 186 | superseded | .claude/worktrees/agent-a0862468b9dbe0fe3 | none taken; owner decision required before any delete |
| worktree-agent-a7dc60dffd573172c | 19d6507 | 2026-10-04 01:35 | Sohom Chatterjee | 224/230 | 11/183 | 30 | 0 | 0 | 186 | superseded | .claude/worktrees/agent-a7dc60dffd573172c | none taken; owner decision required before any delete |
| worktree-agent-af6c9475590ce0449 | 45d4d32 | 2026-09-29 22:55 | Sagexd08 | 122/230 | 6/109 | 7 | 1 | 0 | 121 | has unique work | .claude/worktrees/agent-af6c9475590ce0449 | none taken; owner decision required before any delete |
| ship/mesh-sdk | d6e11ef | 2026-09-29 23:08 | Sagexd08 | 129/230 | 7/112 | 10 | 2 | 0 | 128 | has unique work | .worktrees/mesh-sdk | none taken; owner decision required before any delete |

Totals: 9 superseded, 8 has unique work, 0 needs owner review.

Duplicates: `ship/claim-backtracking` and `ship/real-agent-hardening` share tip `9054bd4`; `worktree-agent-a0862468b9dbe0fe3` and `worktree-agent-a7dc60dffd573172c` share tip `19d6507`. Each pair is reported twice above and counted once in section 4.

Two further local branches appeared while this audit was running, created by another process: `worktree-agent-a9c63b80a5d9062c1` and `worktree-agent-ae0d19d4f859c322b`. Both point at `03f3b74` (= `origin/main`, 0 commits ahead), each has a locked worktree under `.claude/worktrees/`, and neither is in the tables above.

`ship/mesh-sdk` is configured to track `origin/ship/mesh-sdk`, which no longer exists (shown as gone). It is checked out in `.worktrees/mesh-sdk`.

## 4. Unique work found

Across all 36 refs there are 30 distinct `+` commits. Classified by subject, author name and file set:

- 11 are rewritten copies: same subject, same author, file-set overlap 0.92 to 1.00; the only file differences are stripped media files (`.mp4`, `.mp3`, `.png`).
- 1 has a subject match that is not corroborated (`4ac55dc`, "Auto-commit").
- 18 have no counterpart by subject. They are listed below.

In the table, `files same/diff/none` compares each file touched by the commit with `origin/main:<path>`: identical blob / path exists with different content / path absent on main. `lines found` is the share of the commit's non-blank added lines that appear verbatim in the same file on the main tip. `carried by` abbreviates `ship/` to the last path part, `origin/` to `o/` and `worktree-agent-` to `wt-`.

| sha | author | date | subject | files same/diff/none | lines found | carried by |
|---|---|---|---|---|---|---|
| 3b0913c | Sagexd08 | 2026-09-28 | feat(tasks): add interface_consumer and shared_utility_refactor task families | 0/2/7 | 8/312 | integrate, task-families, ui, whitepaper |
| 84347f2 | Sagexd08 | 2026-09-28 | feat(sdk): stamp unstamped events from a logical clock, keep wall time beside the chain | 0/5/0 | 36/236 | integrate, sdk-completion, ui, whitepaper |
| c72f3b4 | Sagexd08 | 2026-09-28 | feat(sdk): optional claim registry and checkpoint handler in sessions | 0/1/1 | 59/356 | integrate, sdk-completion, ui, whitepaper |
| 88ebb47 | Sagexd08 | 2026-09-28 | feat(cli): analyze --edges reports unknown edge counts and resolves endpoints | 0/5/0 | 101/372 | edges-cli, integrate |
| ca2d9ea | Sagexd08 | 2026-09-28 | feat(sdk): export a session's chain and keys, verify it from disk | 0/3/1 | 28/354 | integrate, sdk-completion, ui, whitepaper |
| a4753ba | Sagexd08 | 2026-09-28 | feat(integrations): OpenAI tool_calls and Anthropic tool_use adapters, no framework imports | 0/3/4 | 5/599 | integrate, sdk-completion, ui, whitepaper |
| df162f7 | Sagexd08 | 2026-09-28 | test(tasks): integration tests and gate mutation checks for the two new families | 0/1/0 | 132/378 | integrate, task-families, ui, whitepaper |
| 52f1c8a | Sagexd08 | 2026-09-28 | test: derive task-suite expectations from the registry, not a count | 0/2/0 | 1/32 | integrate, task-families, ui, whitepaper |
| a21a205 | Sagexd08 | 2026-09-28 | docs: describe the four shipped task families | 0/2/0 | 1/13 | integrate, task-families, ui, whitepaper |
| cb4168f | Sagexd08 | 2026-09-28 | docs(sdk): add docs/sdk.md, state that reads are gated only when declared mutating | 0/1/1 | 0/126 | integrate, sdk-completion, ui, whitepaper |
| 7ecffdc | Sagexd08 | 2026-09-28 | test: derive the confirmatory run count from the task registry | 0/1/0 | 1/7 | integrate, task-families, ui, whitepaper |
| f707f37 | Sagexd08 | 2026-09-28 | fix(policy): a bare on: in a checkpoint is a ContractError that says to quote it | 0/2/0 | 7/29 | integrate, ui, whitepaper |
| f37feb9 | Sagexd08 | 2026-09-28 | feat(chain): record the integration test result as a signed event, edge the decision to it | 0/6/0 | 45/130 | edges-cli, integrate |
| 8a964bf | Sagexd08 | 2026-09-29 | feat(web): split agent marks into shipped vs untried, keyboard focus, weight | 0/4/9 | 50/334 | ui |
| 5059c0b | Sagexd08 | 2026-09-29 | feat(web): replace Contact nav link with a Resources dropdown | 0/4/0 | 80/176 | ui |
| 45d4d32 | Sagexd08 | 2026-09-29 | feat(sdk): ship the SDK under the import name mesh | 1/3/3 | 10/122 | mesh-sdk, wt-af6c9475590ce0449 |
| 9021b12 | Sagexd08 | 2026-09-29 | feat(cooperbench): run imported tasks with Claude/Codex via agent_factory | 0/3/3 | 19/377 | mesh-sdk |
| 4ac55dc (c) | ROHIT8759 | 2026-09-30 | Auto-commit | 0/12/4 | 196/1842 | o/feat/scheduler |
| 74ecbfc | Rohit Kumar Kundu | 2026-09-30 | docs: add Antigravity engineering instructions | 0/0/1 | 0/300 | o/dev |

Merge commits are not covered by `git cherry`. Five merges have no subject counterpart on main: `033aafb`, `9d76be5`, `4b5e078` (merges of sibling `ship/*` branches, carried by `integrate`, `ui`, `whitepaper`) and `d6e11ef`, `7af1bdb` (on `ship/mesh-sdk`). They add nothing beyond the commits listed above unless a merge contains a conflict resolution, which this audit did not inspect.

### The three branches previously described as having exactly one unmerged commit

| branch | `+` | (a) copies | (b) | (c) | verdict |
|---|---|---|---|---|---|
| origin/dev | 12 | 11 | 1 | 0 | Confirmed: one commit, `74ecbfc`. |
| origin/feat/scheduler | 11 | 10 | 0 | 1 | Confirmed, with a caveat: one commit, `4ac55dc`, which a subject-only match would have hidden. |
| origin/feature/phase2b-openai-adapter | 4 | 4 | 0 | 0 | Contradicted: zero unique commits found, not one. |

`origin/dev`: `74ecbfc`, author Rohit Kumar Kundu, 2026-09-30 16:56:06 +0530, "docs: add Antigravity engineering instructions"
```
 ANTIGRAVITY.md | 437 +++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 437 insertions(+)
```
`origin/feat/scheduler`: `4ac55dc`, author ROHIT8759, 2026-09-30 15:44:52 +0530, "Auto-commit"
```
 tests/integration/test_run_timeout.py | 415 ++++++++++++++++++++++++++++++++++
 tests/unit/test_run_index.py          |  64 ++++++
 tests/unit/test_scheduler_states.py   |  52 +++++
 tests/unit/test_scheduler_watchdog.py | 350 ++++++++++++++++++++++++++++
 16 files changed, 2137 insertions(+), 30 deletions(-)
```

- `origin/dev`: 218 ahead = 12 `+`, 177 `-`, 29 merges. Of the 12 `+`, 11 have a main counterpart (including `1a6a76c` "Pull all chenges (#9)", counterpart `4c0f39b`, differing only by one stripped `.mp4`). The one without a counterpart adds `ANTIGRAVITY.md`, which is absent from `origin/main`.
- `origin/feat/scheduler`: 152 ahead = 11 `+`, 132 `-`, 9 merges. `4ac55dc` has the generic subject "Auto-commit". Main has 4 commits with that subject by the same author; the best file-set overlap with any of them is 0.00 (no shared file). 196 of 1842 added lines appear on the main tip. The other three "Auto-commit" tips (`feat/evidence`, `feat/packaging`, `feat/server`) are `-`, patch-id equivalent on main.
- `origin/feature/phase2b-openai-adapter`: 103 ahead = 4 `+`, 96 `-`, 3 merges. The 4 `+` commits are `54cd3f4`, `743a69e`, `9d258f6` (file-set overlap 1.00 with main `7ed071b`, `d3dcacf`, `e1cf7b8`) and `19ffe10` (0.97 with main `894da9c`, differing by two stripped media files).

### Limits of the method

- Patch-id matches only an equal diff. A reworded or re-split change has a different patch-id and is reported as `+`.
- Subject matching is exact string equality. A commit whose message was edited during the rewrite shows as (b) although main may hold it; a commit with a generic subject ("Auto-commit") can match an unrelated main commit, which is why (c) exists. Conversely, a different change that happens to share a subject and author with a main commit would be reported as a copy; the file-set test is the guard against that, and it is also a heuristic.
- The added-lines figure is evidence, not proof. A low ratio means the text is not on main verbatim, not that the idea is absent: the feature may have been rewritten on main under other paths.
- Absence of a path on main can mean the path was stripped, renamed or never merged. This audit cannot tell which.
- The 11 commits counted as rewritten copies were not diffed line by line against their counterparts.

## 5. What the history rewrite means for these refs

- `origin/main` is a rewritten history. The first 44 commits (up to `48fcdfa`) kept their hashes; the rest were re-created with new hashes. Every ref in this document still sits on the pre-rewrite history.
- Each ref is therefore 230 commits behind and cannot be fast-forwarded. A merge or rebase would replay pre-rewrite commits whose rewritten twins already exist on main.
- The work that may be unique is the (b) and (c) commits in section 4. Recovering it would be by cherry-pick onto a branch cut from `origin/main`, for example:

```bash
git switch -c recover/<topic> origin/main   # NOT run by this audit
git cherry-pick <sha> [<sha> ...]            # NOT run by this audit
```

- Commits that touch media files stripped from main may not cherry-pick cleanly. A cherry-picked commit keeps its original author line, whatever address that line carries.

### Commits carrying the matching addresses

- Across the 249 distinct commits that are in some audited ref but not on `origin/main`, 210 have an author or committer address at gmail.com or snuindia.in. By author name: Sagexd08 115, ROHIT8759 87, Debojyoti Banerjee 4, Sohom Chatterjee 3, Claude 1.
- `origin/main` itself has 236 of 274 commits matching the same pattern, so these addresses are present on main as well as on the other refs. This audit did not determine which of them, if any, the rewrite was meant to remove.
- Addresses of anyone other than the repo owner are included in these counts and are not to be scrubbed. The scrub scope is undecided; this document only reports counts.

## 6. Preservation

- Pre-rewrite bundle: `C:\Desktop\causalmesh-prerewrite-2026-10-12.bundle` exists (Test-Path true; 190,763,735 bytes, written 2026-10-12 22:53). `git bundle verify` reports it okay with a complete history; `git bundle list-heads` shows 81 refs.
- Every one of the 36 audited refs is in the bundle under the same name at the same tip SHA as today, so the unique commits in section 4 are in it. `main` and `origin/main` differ from the bundle, as expected after the rewrite.
- The bundle also holds 12 remote-tracking refs that no longer exist in this repository (`claude/backlog-implementation-8q6ou6`, `claude/loving-thompson-dhtkkz` and 10 `subagent-*`) and the gone upstream `origin/ship/mesh-sdk`, plus `refs/agents/*` and `refs/codex/*` checkpoint refs. These were not audited.
- All 36 refs listed here still exist; every local one is checked out in a worktree under `.worktrees/` or `.claude/worktrees/`, which is a second place its tip lives.
- No branch is to be deleted before the owner decides. This audit took no action on any ref.
