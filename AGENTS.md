# AGENTS.md

Instructions for coding agents working in this repository.

This project argues that AGENTS.md expresses guidelines and enforces
nothing, and that `causalmesh.yaml` is the enforcement half. Shipping one
without the other would be an odd look, so both live here and this file is
the guidelines half.

## Commands

```bash
pip install -e ".[dev,analysis]"   # set up
pytest -q                          # full suite, ~10-15 minutes
pytest -q --ignore=tests/integration   # faster, skips subprocess tests
pytest -m unit -q                  # fastest inner loop
ruff check src tests               # lint, must pass
ruff format src tests              # format, must be clean
python scripts/check.py            # the whole local gate in one command
causalmesh doctor                  # what this machine has and lacks
```

There is no CI. `python scripts/check.py` is the gate (lint, format, types on
the enforced modules, the security scan and the suite) and it must pass before
a change is merged. It tests the one machine it runs on: Windows, Linux and
macOS each need a run of their own, and the site has its own check
(`npm run types:check && npm run build`).

## Layout

| Path | What lives there |
|---|---|
| `src/causalmesh/` | the substrate. Everything shipped. |
| `src/causalmesh/policy/` | contract, gate, ledger, resources |
| `src/causalmesh/claims/` | the claim registry (exclusive leases) |
| `src/causalmesh/crypto/` | Ed25519 signing and the hash chain |
| `src/causalmesh/cli/` | the `causalmesh` command |
| `src/causalmesh/tui/` | terminal surfaces |
| `tests/` | the suite, marked by kind |
| `fixtures/` | experimental material. **Do not lint or reformat.** |
| `frontend/` | the whole website: `/` and `/docs` |
| `docs/` | architecture, protocol, security, and the backlog |

## Rules

**Do not touch `fixtures/`.** They are git checkouts copied into agent
workspaces and edited by agents under test. Linting them lets tooling
silently rewrite the thing being studied. `ruff --fix` did exactly that
once, stripping `noqa` directives the fixture needs when it runs as a
standalone repository.

**Nothing non-reproducible in the signed chain.** The chain is
bit-reproducible. Hostnames, wall-clock time, absolute paths and random ids
go in the run artifact's envelope, outside the signature.

**An absent field is `unknown`, never `0`.** A counter that reports a
confident zero is worse than a missing one. This project has shipped that
bug; `docs/backlog.md` records it.

**Money is `Decimal`.** Floats are rejected at the call site. Ledger amounts
are stored as strings and summed in Python, not SQL.

**A refusal is data.** `ClaimOutcome` and `Verdict` are returned, not
raised. Keep `may_write` (a question) apart from `record_denial` (a
statement that an attempt was refused).

**Terminal output is ASCII.** Windows consoles default to cp1252, and a
non-ASCII character in a table header raises `UnicodeEncodeError` mid-render.
Ask the console what it can encode; never infer from the platform.

**Record what is not built.** `docs/backlog.md` takes an entry for every
gap, with its reason. An honest gap is tracked; a silent one is a defect.

## Field names that are easy to get wrong

Both have cost a debugging cycle, and both fail as a plausible-looking zero
rather than as an error:

- actor id is `event.identity.agent_id`, **not** `event.actor_id`
- run success is `result.outcome.succeeded`, **not** `result.success`

## Testing

Assert the fact a surface must show, not the exact characters it renders
today. A test pinned to a rendered string turns every layout improvement
into a test change. `tests/unit/test_tui.py` explains this in its docstring.

Markers are enforced (`--strict-markers`): `unit`, `integration`,
`property`, `adversarial`, `failure`, `reproducibility`, `slow`.

## What not to do

- Do not add a runtime dependency without a reason that survives the
  question "what does this cost a person installing the package". The
  runtime core is deliberately light; the analysis stack is a separate
  extra.
- Do not add a second UI framework. The terminal surfaces are `rich`, which
  is already a dependency.
- Do not claim anything about agent behaviour. Every run so far used a
  deterministic mock agent.
