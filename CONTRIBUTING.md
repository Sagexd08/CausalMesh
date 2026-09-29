# Contributing to CausalMesh

Thank you for looking. This document says how to get the project running,
what the tests expect, and the few rules that are non-negotiable because the
project's central claim depends on them.

## Before you open a pull request: open an issue first

Direct pushes to `main` are restricted to the project owner. Everyone else —
including existing collaborators — merges through a reviewed pull request,
and every pull request traces back to an issue:

1. **Open an issue** describing the bug or the change you want to make.
   Use the templates under `.github/ISSUE_TEMPLATE/`.
2. **Wait for it to be triaged.** A maintainer will accept it (label it and
   assign it to you) or explain why it does not fit — see "What this project
   is not looking for" below for the kinds of change that tend not to.
3. **Open the pull request only once the issue is assigned to you.**
   Reference the issue number in the PR description (`Fixes #123` or
   `Refs #123`). A pull request with no linked, accepted issue will be asked
   to open one before review continues.

This exists so that design disagreements — which arm a change affects,
whether it touches the signed chain, whether it belongs in the runtime core
or the analysis extra — surface before code is written, not in review after
the work is already done. It also keeps two people from independently
building the same thing, which has happened in this project's own history.

A trivial fix (a typo, a broken link, a stale claim in a doc) does not need
the full round trip; open the PR and say so, and a maintainer will judge
whether the issue step actually mattered here.

## Getting it running

```bash
git clone https://github.com/Sagexd08/CausalMesh
cd CausalMesh
pip install -e ".[dev,analysis]"

causalmesh doctor          # reports what this machine has and lacks
pytest -q                  # the full suite, about three minutes
```

`doctor` is the fastest way to find out whether a failure is your
environment or the code. It names what is missing rather than failing
generically.

To see the substrate do something:

```bash
causalmesh experiment run --profile smoke   # four arms, one task, ~a minute
causalmesh verify --latest                  # every chain, offline
causalmesh analyze --latest                 # what each arm bought and cost
```

## Before you open a pull request

```bash
ruff check src tests          # must pass
ruff format src tests         # must be clean
pytest -q                     # must pass
python scripts/check.py       # all of the above, plus types and the security scan
```

There is no CI, so run the gate yourself, and on Windows if you can: the
isolation layer and the terminal interface both behave differently there,
and both have shipped bugs that only appeared on it. The site has its own
check: `npm run types:check && npm run build`.

## The rules that are not style preferences

These exist because the project makes a specific claim, and each of them is
load-bearing for that claim.

### Nothing non-reproducible enters the signed chain

The chain is bit-reproducible. A hostname, a wall-clock timestamp, an
absolute path or a random id inside the signed payload breaks that, and the
breakage is silent until someone tries to verify a run on another machine.

Provenance belongs in the run artifact's **envelope**, which is outside the
signature. If you need to record where something ran, that is where it goes.

### A measurement must be able to observe its subject

The worst bug this project has had was an enforcement counter that reported
a confident zero while enforcement was working correctly: denials were
written by one code path and the gate refused through another.

So when you add a counter over run artifacts, an absent field is `unknown`,
never `0`. A wrong number that looks plausible is worse than a missing one,
because nobody goes looking for it.

### A refusal is data, not an exception

The claim registry returns a `ClaimOutcome` and the gate returns a
`Verdict`. Neither raises on a denial. That is deliberate: the denial record
is the primary measurement of enforcement, and raising would push every call
site into deciding what to log.

`may_write` answers a question and may be asked speculatively.
`record_denial` states that a real attempt was refused. Keep them apart, or
the denial count starts measuring how often the gate was consulted.

### Money is `Decimal`, end to end

A float budget drifts by fractions of a cent until it silently does not
hold. Amounts are rejected at the call site if they arrive as floats, stored
as strings, and summed in Python rather than in SQL, because SQLite would
coerce the column to a float to add it.

### Documentation states what is not built

`docs/backlog.md` records every known gap with its reason. If your change
falls short of what a reader would assume from the code, add the entry. An
honest gap is a tracked item; a silent one is a defect.

## Tests

The suite is marked by kind, and the markers are enforced
(`--strict-markers`):

| Marker | What it covers |
|---|---|
| `unit` | isolated components |
| `integration` | real subprocesses, real HTTP, cross-component paths |
| `property` | invariants, driven by Hypothesis |
| `adversarial` | attacks the verifier must detect |
| `failure` | fault injection and recovery |
| `reproducibility` | same seed and config produce equivalent structure |
| `slow` | more than a few seconds |

```bash
pytest -m unit -q                    # fast inner loop
pytest -m adversarial -q             # the tamper-detection suite
pytest -q --ignore=tests/integration # everything but the slow half
```

A test that asserts an exact rendered string will break the first time
someone improves a layout. Assert the fact the surface must show, not the
characters it happens to use today. `tests/unit/test_tui.py` says this in
its own docstring and is worth reading before you write terminal tests.

## Commit messages

Say what changed and why it was wrong before. The commit log is where the
reasoning lives for decisions that are not obvious from the diff, and most
of this project's interesting decisions are not.

Conventional-commit prefixes (`feat:`, `fix:`, `docs:`, `refactor:`,
`test:`, `chore:`) are used but not enforced.

## Reporting something

- **A bug**: what you ran, what happened, what you expected, and the output
  of `causalmesh doctor`.
- **A security issue**: see [SECURITY.md](SECURITY.md). Do not open a public
  issue for one.
- **A measurement you think is wrong**: this is the most valuable kind of
  report this project can receive. Say which number, and what you think it
  should be. Every figure on the site and in the docs comes from a run
  artifact, so the disagreement can always be settled by pointing at one.

## What this project is not looking for

- **A new orchestration library.** The value here is the layer underneath
  one. Working with LangGraph beats replacing it.
- **Benchmarks against other frameworks** without the methodology to support
  them. This project's whole argument is that measurement is the hard part.
- **Claims about agent behaviour.** Every run reported so far used a
  deterministic mock agent. Nothing here supports a claim about how real
  coding agents coordinate, and the documentation says so in several places.
