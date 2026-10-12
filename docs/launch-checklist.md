# Launch checklist: v0.1.0, 2026-10-09

Written for: the repository owner, who is launching this on the 9th and needs
to know what is true, what is blocking, and what will not be done in time.
Every status below was checked on 2026-10-08 against `main` at `19d6507` plus
the two fixes noted under "Done today". Re-run the check named beside a line
before you rely on it.

## What launches

| Surface | Launching | How a person gets it |
|---|---|---|
| **The `causalmesh` package, 0.1.0, Pre-Alpha** | the SDK, the gate, `serve`, `verify`, the CLI | `pip install causalmesh` |
| **The experiment harness** | the repository only | `git clone`. The wheel carries no `fixtures/` or `tasks/`, on purpose (`MANIFEST.in`); `causalmesh quickstart` says so and points at the clone. |
| **The site** | `/` and `/docs` | `causalmesh.vercel.app` |
| **The repository** | public, MIT | `github.com/Sagexd08/CausalMesh` |

What the launch may claim: the substrate is built and tested, and a refusal is
signed evidence a stranger can verify offline. What it may not claim: anything
about how real coding agents behave. Every run so far used a deterministic mock
agent and no hosted model has driven anything (`AGENTS.md`, `docs/backlog.md`).

## Blockers: must be true before anything is published

| # | Item | Status | Check / action |
|---|---|---|---|
| 1 | **The gate is green on the commit you tag** | *Fixed today, final run pending.* `main` failed mypy (4 errors in `gateway/gateway.py`) and one test could not be collected here (`tests.integration` resolved to another installed package's `tests`). Both fixed. | `python scripts/check.py` on the exact commit. Record the pass count here: **___ passed** |
| 2 | **Decide the git history before the repo goes public** | **Your decision.** Three commits (`54cd3f4`, `743a69e`, `9d258f6`) hold a contributor's hostname and OS username in `data/manifests/pilot_landing.manifest.json`. The current tree is clean. Details: `docs/backlog.md`, "The pilot manifest named a person's host and username". | Rewriting (`git filter-repo`) changes every later hash and breaks every clone and open branch, including Rohit's and Debojyoti's, and Vercel's deploy history. It is cheapest *now*, while the repo is private. Not rewriting is a legitimate choice if you accept those strings being public forever. Make the choice before step 3, because making the repo public is the point of no return. |
| 3 | **The repo is public** | **It is private today** (`gh repo view`). Until it is public, the site's links, `pyproject.toml`'s URLs, the `quickstart` hint (`git clone ...`) and the launch post all 404 for everyone else. | `gh repo edit Sagexd08/CausalMesh --visibility public --accept-visibility-change-consequences` after #2. Then add topics and the description. |
| 4 | **Secrets** | Clear on the checks run today: every added line in all history was scanned for key, token and private-key patterns; the only matches are deliberate fake values in tests. `.env.example` is the only env file tracked. | For a second opinion before going public, run `gitleaks detect` or `trufflehog git file://.`; neither is installed here. |
| 5 | **PyPI name and token** | `causalmesh` is **free** on PyPI (404 on 2026-10-07; re-check). No token exists in this environment. | Create the project's API token at pypi.org. `.github/workflows/publish.yml` will **not** run: Actions have been disabled by a billing failure since 2026-09-28. Publish by hand (see the runbook). |
| 6 | **The built artifacts are sound** | Built from current `main`: `causalmesh-0.1.0.tar.gz` and `-py3-none-any.whl`, **`twine check` PASSED on both**. A clean venv installs the wheel with `[server]`; `causalmesh --version` prints 0.1.0; `quickstart` explains the harness needs a checkout; `serve --dev` answers `/healthz` 200 and `/v1/tools` 200. | Repeat on the tagged commit. Install from **TestPyPI** in a clean venv before the real upload. |
| 7 | **Version and changelog** | `__version__` is `0.1.0` (single-sourced). `CHANGELOG.md` still says `## [Unreleased]`. | Rename it `## [0.1.0] - 2026-10-09` and add a fresh empty `[Unreleased]`. |
| 8 | **The launch post is true** | **Stale.** `docs/launch-post.md` says "865 tests", "~40% built" and "Next week: the CLI". The CLI exists. | Replace posts 13 and 14 and the "Notes on claims" with current, checkable numbers (see below). Do not post a number that is not in the notes. |
| 9 | **The site deploys from the final commit** | Production is READY on `19d6507` (deployment `dpl_2E6m...`). It must be redeployed from the commit you tag. The site **cannot be built on this Windows machine** (Application Control blocks `yuku-analyzer`), so the proof is Vercel's own build or a Linux container. | Push to `main`, confirm the Vercel build is READY, then load `/`, `/docs`, `/docs/limitations`, `/docs/quickstart`. Run the checklist's copy audit below. |

### Copy audit for the site and README (do before pushing)

- Every number resolves to something in the repo (`frontend/lib/landing/results.json`
  comes from `data/raw/pilot_landing/`, which is **24 runs of a mock agent**).
- No sentence says or implies a hosted model drove a run.
- `frontend/content/docs/limitations.mdx` lists what is not built: `report`, the
  staleness estimators, a hosted-model run, the 1920-run collection.
- `README.md` has a `pip install causalmesh` path as well as the `pip install -e .`
  contributor path, and says plainly that the harness needs a clone.

## Done today (2026-10-08)

- Fast-forwarded the local checkout: it was **75 commits behind `origin/main`**
  (the SDK export, claims, `serve --tools`, token lifecycle, the Anthropic,
  LangGraph and CrewAI adapters and the real-data CooperBench work were all missing
  locally). Anything checked against the old tree was discarded.
- `src/causalmesh/gateway/gateway.py`: the duck-typed `_MutatingAwareCall` was annotated
  as `ToolCall`, so mypy rejected `.reservations` four times. Annotated `Any`. No
  behaviour change.
- `tests/integration/test_scheduler_interrupt.py`: imported a sibling test as
  `tests.integration.test_scheduler_loop`, which resolves to whichever package named
  `tests` is first on `sys.path`. Every other test imports siblings by bare name; this
  one now does too.

## Not happening by the 9th, and why

None of these is hidden: each already has an entry in `docs/backlog.md`. They are
listed here so nobody mistakes the launch for having closed them.

| Backlog item | Why it cannot be finished from code in a day | What it needs |
|---|---|---|
| A real hosted model driving a task | Needs an API key and a budget; spending is the owner's call. | A key, a ceiling, an afternoon. **The single most valuable post-launch step**: until it happens, the project can say nothing about agent behaviour. |
| The 1920-run confirmatory collection | The gate is closed on purpose. It commits to a preregistered analysis, and `docs/preregistration-draft.md` is an unsigned draft full of `TODO(owner)`. | Decisions only the owner can make, then compute. |
| Multi-rater kappa coding | The code exists; the raters do not. | At least two people reading transcripts independently. |
| Staleness estimators (lambda-hat, delta-hat, Delta-hat) | The defining text (spec sections 23 and 45) is not in the repository. `docs/staleness-estimators-needed.md` says exactly what to supply. Inventing them is what the backlog forbids. | The spec text. |
| `causalmesh report` | Waits on the empty `reporting/` subsystem. `doctor` says so. | Design work; a post-launch feature. |
| CrewAI adapter against real `crewai`; LangGraph at its declared floor | Heavy installs; the real-package tests skip when absent. | An afternoon in a clean environment. |
| Linux and macOS test runs | The gate tests only the machine it runs on and there is no CI. | See "Worth doing today" below. |
| Runner leases keyed on raw paths (`ContractGate` claim rule never fires on them in runs) | Fixing it changes what contract-gated C3 runs measure. A decision for the experiment's owner, not a patch. | A decision, then a small change and a re-gate. |
| Chat path still signs the wall clock; `verify --keyring`; approved checkpoints on the chain; export on `serve` shutdown | Each is real work touching the signed chain; each is recorded with its reasoning. | Post-launch, one at a time, each with a mutation-checked test. |
| Parallel runs, Docker as a C0 jail, scaling beyond 4 agents (profile) | Measurement-validity and platform questions, not mechanism. | Linux, and a decision. |
| Registry image, TLS termination, no hosted CI | Money or infrastructure. | Optional. |

## Worth doing today if you have the hours

1. **A Linux run of the gate** (the cheapest corroboration available, and the first
   result from a second machine): in a clean `python:3.12` container,
   `pip install -e ".[dev,analysis,server,langchain]" && python scripts/check.py`.
   Docker Desktop is on this machine.
2. **A fresh-clone test**: clone the public repo into an empty folder on a machine
   that has never seen it and follow only the README. The first stumble is the first
   issue a stranger would file.
3. **One hosted-model smoke run** with a small spend ceiling, written up exactly as it
   happened, failure rate included. Not required to launch; the launch must then say
   "a single run" and not "the system works with models".

## Runbook: the 9th

```bash
# 0. on the commit to be tagged
git pull --ff-only && python scripts/check.py            # must pass; record the count above

# 1. changelog -> 0.1.0, commit
git commit -am "release: 0.1.0" && git tag -a v0.1.0 -m "0.1.0 (Pre-Alpha)"

# 2. build and inspect
python -m build --outdir dist && python -m twine check dist/*

# 3. TestPyPI first, then a clean-venv install from it
python -m twine upload --repository testpypi dist/*
python -m venv /tmp/t && /tmp/t/bin/pip install -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple "causalmesh[server]" && /tmp/t/bin/causalmesh --version

# 4. only after #2 in "Blockers" is decided: go public, push, release
gh repo edit Sagexd08/CausalMesh --visibility public --accept-visibility-change-consequences
git push origin main --tags
gh release create v0.1.0 --title "0.1.0 (Pre-Alpha)" --notes-file <(sed -n '/## \[0.1.0\]/,/## \[0/p' CHANGELOG.md)

# 5. the real upload (username __token__, password = the PyPI token)
python -m twine upload dist/*
pip install causalmesh==0.1.0                              # from a clean venv, one more time

# 6. confirm the site, then post
#    https://causalmesh.vercel.app  -> /, /docs, /docs/quickstart, /docs/limitations
```

A PyPI release cannot be replaced, only yanked: a wrong 0.1.0 means shipping 0.1.1.
That is the reason for TestPyPI first.

## After the launch

- Watch the issue tracker; the first strangers' installs are the real test of
  `quickstart`, `doctor` and `init`.
- Run the hosted-model smoke test and publish the result either way.
- Pick the `docs/backlog.md` items above in the order people actually ask for them.
