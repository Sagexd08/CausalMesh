# Changelog

Notable changes, newest first. This project is pre-1.0 and follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
[semantic](https://semver.org/spec/v2.0.0.html) once there is one to break.

An entry here says what changed for someone using the project. What changed
inside it is in the commit log, and what is deliberately absent is in
[`docs/backlog.md`](docs/backlog.md).

## [Unreleased]

### Added

- **The policy plane.** A declared contract (`causalmesh.yaml`) read by a
  gate that allows or refuses, and a ledger that records what has been
  consumed across processes. Four resource kinds: paths, spend, endpoints
  and budgets. A refused write and a refused payment are the same event, so
  they are the same type.
- **`causalmesh policy init | show | check`.** `check` asks the gate whether
  an action would be allowed, without running an agent or spending anything.
  It exits 0 when allowed and 1 when refused, and records nothing.
- **Contract-driven runs.** `RunConfig.contract_path` installs `ContractGate`
  in place of the arm's own gate. Without a contract nothing changes, because
  the C2 to C3 contrast is only clean if the two arms differ by one factor.
- **The rule that refused, in the signed chain.** Denials were already signed
  evidence carrying a reason, a holder and a blocked path. They now also
  carry a stable rule identifier, so analysis can group refusals by rule
  instead of parsing an English sentence that changes when the wording
  improves.
- **CI.** Lint, format, the suite across Linux, Windows and macOS on two
  Python versions, a security scan, an evidence job that produces a
  collection and verifies it, and the site build.
- **Contributor documentation.** `CONTRIBUTING.md`, `SECURITY.md`,
  `AGENTS.md`, issue and pull-request templates.
- **A contract for this repository.** The project argues that AGENTS.md
  enforces nothing and a contract is the enforcement half, so it ships both.

### Fixed

- **The model transport opened any URL `urllib` had a handler for.** A
  `file://` base URL reaching it from a config or an environment variable
  would have read a local path and returned its contents as a model reply,
  which the agent layer would have treated as a decision the model made.
  Only `http` and `https` are permitted now. Found by a static scan rather
  than by a failing test, which is the argument for running one.
- **A lease refusal was not recorded as a denial.** The contract gate
  consulted leases through `may_write`, which deliberately records nothing,
  so enforcement could work while the counter reported zero. This is the
  same defect class recorded in the backlog, caught by the gate's own tests
  before it reached a run.
- **Eighteen integration tests failed on a fresh checkout.** They read the
  committed pilot, and `data/raw/**` is gitignored, so CI and every clone
  had no evidence to read. They skip with a reason now rather than failing
  as though the CLI were broken.
- **Linting ran against whatever version was newest that morning.** Ruff and
  mypy are pinned, so a pull request that changed nothing cannot fail on a
  rule that did not exist when it was opened.
- **Line endings churned between platforms.** `.gitattributes` normalises
  text to LF. On a bit-reproducible chain, a fixture whose line endings
  change underfoot hashes differently on one platform than another.

### Changed

- The website moved from `docs-site/` to `frontend/`. The directory held the
  whole site, landing page included, so the old name described a part as the
  whole. Vercel's framework detection was also failing, because it looks for
  `next` in the root `package.json` and a workspace layout does not put it
  there.

## Before this file existed

The build sequence through Step 10 and Phase 1 is recorded in
[`docs/PLAN.md`](docs/PLAN.md), and the measured pilot in
[`docs/results`](frontend/content/docs/results.mdx). Briefly: the coordination
substrate, the signed chain, the claim registry, the four arms, the CLI, the
provenance layer, the connectors and the terminal interface, each with its
tests, followed by a 24-run pilot whose every chain verifies offline.
