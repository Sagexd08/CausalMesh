# Name migration: CausalMesh -> Lockwright (PROVISIONAL)

Status: **provisional.** Nothing here is trademark or legal clearance. The new
name was chosen from registry and web checks run on 2026-10-12 and 2026-10-13.
No external action has been taken: the GitHub repository, the PyPI project
`causalmesh` and every URL are unchanged, and no package named `lockwright`
has been published.

## Why rename

`VictorAgahi/causalmesh` is a public project with overlapping positioning
(an MCP/atlas product under the same name), recorded as an open owner question
in `docs/SHIP-AUDIT.md` (Section 8, item 1) and `docs/ship-log/PHASE-A.md`
(item 1). This task's brief directed that the product not keep a confusingly
similar identity. The owner's own decision record on the name was not found in
the repository; this document is the record of the choice and its evidence.

## What the name has to be

Distinct from `causalmesh`; free on the registries this project would use;
no exact-name GitHub repository or account; no existing developer tool with the
same or a near-identical name; and not carrying an unrelated connotation.
"Lock" says what the Track B work is for (exclusive write leases); "wright"
(a maker of a thing) keeps it a noun and not a verb. It does not promise more
than exists: nothing in the name says "atlas", "memory" or "graph".

## Checks performed

Retrieval dates: registry and GitHub API checks **2026-10-12 (UTC)**; web
searches **2026-10-13**. All 30 candidates were lowercase letters only, so the
normalized form equals the exact name.

| Check | Endpoint | Result for `lockwright` |
|---|---|---|
| PyPI exact | `GET https://pypi.org/pypi/lockwright/json` | 404 (free) |
| npm exact | `GET https://registry.npmjs.org/lockwright` | 404 (free) |
| crates.io exact | `GET https://crates.io/api/v1/crates/lockwright` | 404 (free) |
| GitHub repo-name search | `GET https://api.github.com/search/repositories?q=lockwright+in:name` | `total_count` 0 |
| GitHub user/org exact | `GET https://api.github.com/users/lockwright` | 404 (free) |
| Web search | "lockwright software OR cli OR python" | no product, library or CLI of that name; only generic CLI-library results |

Candidates also free on PyPI, npm and crates.io, with zero GitHub repository
hits and no exact-name account: `warrantline`, `writgate`, `plumbgate`,
`tesseragate`, `warrantmesh`, `deedmesh`, `covenantkit`, `plotgate`,
`titlegate`. Why they lost:

- `writgate`, `plumbgate`, `tesseragate`, `plotgate`, `titlegate`: the
  `-gate` suffix reads as a scandal name. A web search for `writgate` and
  `plumbgate` returned only Watergate-family results.
- `warrantmesh`, `deedmesh`: keep `mesh`, which is the part that collides with
  the existing name.
- `covenantkit`: "Covenant" is the name of a well-known penetration-testing
  command-and-control framework; a developer tool by that name invites a
  security-tool misreading.
- `warrantline`: free everywhere and no hits, but its web results are
  warranty-management software, which is noise for a developer tool.
- `boundmark`: free and no hits, but it says nothing about what the tool does.

Excluded because a registry or GitHub check failed (PyPI / npm / exact-name
GitHub repo or account): `fenceline`, `claimgate`, `agentwarden`, `tallyline`,
`seamark`, `markgate`, `ledgerline`, `gatewright`, `lienmark`, `leasekit`,
`wicketgate`, `stakegate`, `claimwright`, `quorumline`, `sealgate`,
`deedkeeper`, `stakehold`, `writwright`.

Raw responses are not committed. The full 30-row table was produced by a
read-only scout on 2026-10-12 and is reproducible with the five endpoints above.

## What was NOT checked (remaining uncertainty)

- **Trademark.** No USPTO, EUIPO, WIPO or national register was searched, and
  no confusingly-similar-mark analysis was done. Use a trademark search before
  any commercial use.
- **Exact-name GitHub repositories beyond the top 5 search hits.** The
  `total_count` for `lockwright` is 0, so this does not affect it, but the
  ranking of the other candidates inherits the limit.
- **Other registries and marketplaces**: conda-forge, Homebrew, Debian,
  Docker Hub, the VS Code Marketplace, RubyGems, NuGet, Maven, Go modules.
- **Domains.** None is part of the approved launch plan, so none was checked.
- **Non-English meanings** and search-engine ranking.
- **Similar-sounding developer tools.** "-wright" is also the suffix of
  Playwright (Microsoft). The names are not the same, but a reader skimming
  could assume a relation. This is a judgement, not a measured confusion.
- A name checked as free today can be taken tomorrow; nothing was reserved.

## What changes and what deliberately does not

| Surface | Decision | Reason |
|---|---|---|
| Product name in README, docs, site copy, CLI help and banners | **renamed** to Lockwright | user-facing identity |
| Distribution name in `pyproject.toml` | **renamed** to `lockwright` | unpublished, so no user is stranded; the `causalmesh` 0.1.0 files stay on PyPI |
| Console script | **both** `lockwright` and `causalmesh` entry points | existing hook examples, scripts and docs call `causalmesh` |
| Python import package `causalmesh` | **not renamed** | public API; renaming breaks every integrator and the SDK import path |
| Event schemas, signature domain strings, hash-chain formats, persisted field names | **not renamed** | would invalidate existing signed evidence |
| Contract filename `causalmesh.yaml`, `.causalmesh/` directory, env vars `CAUSALMESH_*` | **not renamed** | persisted user configuration; a rename needs a dual-read period and tests (tracked in `docs/backlog.md`) |
| GitHub repository `Sagexd08/CausalMesh`, GitHub Pages/site URLs | **not changed** | external action; not authorized by this task |
| PyPI project `causalmesh` 0.1.0 | **unchanged** | cannot be unpublished or re-uploaded |

Consequence the owner should know: after this change the **import name and the
distribution name differ** (`pip install lockwright`, `import causalmesh`),
the same way `pip install scikit-learn` provides `import sklearn`. That is a
deliberate trade for not breaking evidence and integrators.

## Migration path for existing users

1. Nothing changes for anyone who installed `causalmesh==0.1.0`: the
   import name, the `causalmesh` command, `causalmesh.yaml` and every signed
   artifact keep working.
2. To move to the new distribution once it is published: `pip uninstall
   causalmesh && pip install lockwright`. The `causalmesh` command remains as
   an alias, so scripts, hook settings and CI do not need to change.
3. Publishing is an owner step and has not happened. When it does, the
   recommended order is: publish `lockwright` first, verify a fresh install,
   then publish one final `causalmesh` release that only depends on
   `lockwright`, and state the move in its description.
4. A dual-read contract filename (`lockwright.yaml` preferred, `causalmesh.yaml`
   accepted) is the next compatibility step; it is not built (backlog).

## Tests that pin the compatibility promise

See `tests/unit/test_name_migration.py`: both console scripts resolve to the
same entry point, `--version` reports the product name and the distribution
version, and the import package, the contract filename and the signature
domain strings are unchanged.

## Reverting

The rename is one commit. `git revert <that commit>` restores the old
identity; nothing outside the repository was touched.
