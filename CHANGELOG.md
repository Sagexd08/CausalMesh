# Changelog

Notable changes, newest first. This project is pre-1.0 and follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
[semantic](https://semver.org/spec/v2.0.0.html) once there is one to break.

An entry here says what changed for someone using the project. What changed
inside it is in the commit log, and what is deliberately absent is in
[`docs/backlog.md`](docs/backlog.md).

## [Unreleased]

### Added

- **Developer SDK and tool gateway.** `CausalMesh`, `Tool` and `ToolGateway`
  put the existing gate in front of an operator's own tools, sync and async.
  Tools are gated unless declared `mutating=False`; protected resources come
  from explicit `resource_args`, and a missing one fails closed.
- **`causalmesh serve` on FastAPI** (`pip install 'causalmesh[server]'`):
  `/v1/tools`, `/v1/tools/{name}/execute`, `/v1/chat/completions`, bearer
  authentication, and `--dev` (no auth) refused for any non-localhost host.
- **Framework adapters** for OpenAI function calling and LangChain
  (`langchain-core` optional), both routed through `CausalMesh.execute`.
  Tested with mocks only; no hosted model or real framework agent loop was run.

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
- **Contributor documentation.** `CONTRIBUTING.md`, `SECURITY.md`,
  `AGENTS.md`, issue and pull-request templates.
- **A contract for this repository.** The project argues that AGENTS.md
  enforces nothing and a contract is the enforcement half, so it ships both.
- **A local gate.** `python scripts/check.py` (or `make check`) runs lint,
  format, mypy on the enforced modules, bandit and the full suite. There is
  no CI, so this is the only enforcement; a tool that is not installed fails
  it rather than being skipped.

### Fixed

- **Ownership could be walked around by spelling.** `allowed/../forbidden/x`,
  `./forbidden/x`, `Forbidden/x`, `forbidden./x` and an absolute path inside the
  repository were all allowed where `forbidden/x` was refused. Paths are now decided
  on the canonical file, and a resource argument that is not text is refused (a list
  used to be checked as one odd string while the handler received both paths).
- **The SDK could not express a spend, an endpoint or a budget.** A tool that reached
  a network or spent money ran with no policy decision. `Tool(resource_kind=...,
  amount_arg=...)` now hands the gate every kind; totals need `CausalMesh(ledger=)`
  and are refused without one.
- **A checkout at an ordinary Windows path failed every run.** The run id was in the
  workspace path twice, so 48 characters of checkout plus a 29-character experiment
  id overflowed MAX_PATH with an error that did not mention length. Fixed, and a
  run that still cannot fit is refused up front with the numbers.
- **`/v1/chat/completions` lost records under concurrency.** Event ids came from the
  clock, so two requests in one tick shared an id and the second went unrecorded
  while still being forwarded. Ids carry a sequence number, and an allowed call that
  cannot be recorded is not forwarded.
- **Server hardening.** Non-root container with a health check; docs and schema only
  in dev mode; 1 MiB body limit; opt-in rate limit; slow handlers and upstream calls
  no longer stall the event loop; a handler's exception text, an object's attributes
  and the known-agent list no longer reach clients; upstream redirects are refused.
- **Dependency floors admitted known advisories and unbuildable versions.**
  `cryptography>=41.0` (14 advisories), `starlette` 0.37 (7), `PyYAML>=6.0` and the
  analysis floors had no wheel for Python 3.12 or 3.13. Raised deliberately; the
  suite passes at exactly the floors.
- **The gate could pass while skipping the server tests.** `scripts/check.py` now
  fails when an optional dependency the tests need is missing.
- **An async tool call ran for an agent the session had no key for.**
  `execute_async` skipped the unknown-agent check `execute` makes, so the
  handler ran and the call went unrecorded, and `/v1/tools/{name}/execute`
  answered 200 for it. That path is also the one every adapter's async method
  takes. Both paths now share one check and raise `UnknownAgentError` (HTTP
  400) before the gate or the handler is reached.
- **`/v1/chat/completions` trusted the caller's agent name.** An agent with no
  key matched no role, so it skipped that role's allowlist, was forwarded, and
  left no record. It is refused with 400. A body that is not a JSON object, or
  a `model` that is not a string (a float has no canonical form in the chain),
  returns 400 instead of 500, and an unreachable or non-JSON upstream returns
  502 instead of 200 with an error body.
- **`--upstream` accepted any URL scheme, and the allowlisted host came from a
  string split.** `file://` and other non-HTTP schemes are refused at startup.
  The host is taken from the parsed URL, so `http://evil.example#.api.example.com`
  is checked as `evil.example` and not as a subdomain of the allowed host.
- **`create_app` served without authentication when called without
  `api_tokens`.** Authentication is now an explicit choice (`api_tokens=` or
  `auth_disabled=True`), blank tokens are refused, tokens are compared in
  constant time, and a 401 carries `WWW-Authenticate: Bearer`.
  `serve --dev --api-token X` no longer switches the supplied token off.
- **`OpenAIAdapter` raised on model mistakes.** An unknown tool name, a missing
  resource argument or non-object arguments now come back as an `Action
  failed:` tool message, as malformed JSON already did. An unknown *agent*
  still raises, because the developer chose it, not the model.
- **The Docker image could not start `serve`.** It installed no
  `fastapi`/`uvicorn`, and `docker-compose.yml` passed no API token. It now
  installs `.[server]` and reads `CAUSALMESH_API_TOKEN`.
- **`causalmesh serve --api-token ""` started with authentication off.** A
  blank token (for example from an unset shell variable) passed the "token
  required" check and then left the server with no valid tokens, so
  `/v1/tools` answered 200 to anyone on `--host 0.0.0.0`. A blank or
  whitespace token is now treated as no token.
- **CLI error text was parsed as Rich markup.** `pip install
  'causalmesh[server]'` printed as `pip install 'causalmesh'`, and an error
  message containing a stray `[/tag]` raised `MarkupError` inside the error
  reporter. `fail`, `warn` and `note` now escape their text.
- **`causalmesh doctor` called the adversarial battery "not built"** because
  it inspected an empty `src/` package; the battery is `tests/adversarial`.
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

### Added (agent identity)

- **Per-agent tokens.** `causalmesh serve --agent-token AGENT=TOKEN` (repeatable, or
  `CAUSALMESH_AGENT_TOKENS`) binds a token to one agent: the server takes the agent
  from the token and refuses a request that names another. `--max-body-bytes`,
  `--rate-limit` and a `langchain` extra are new. `/execute` returns the handler's
  value.

### Changed

- `/execute` and chat answer `502`, not `200`, when the upstream fails, and `400`
  for an unknown agent, with no list of the agents that do exist.
- The website moved from `docs-site/` to `frontend/`. The directory held the
  whole site, landing page included, so the old name described a part as the
  whole. Vercel's framework detection was also failing, because it looks for
  `next` in the root `package.json` and a workspace layout does not put it
  there.

### Removed

- **`adapters/serve.py`**, the stdlib `http.server` implementation of `serve`, with
  the tests that existed only for it. Nothing reached it, it had no authentication,
  and it still carried defects fixed in the live server.
- The Makefile's `report` and `reproduce` targets, which called commands that do not
  exist, and seven session artifacts at the repository root.
- **The GitHub Actions workflow.** Hosted runners were not worth paying for, and
  the workflow had not started a job since 2026-09-28 (the account's payments
  had failed). Nothing replaces the remote runs; `python scripts/check.py` is
  the local gate. See `docs/backlog.md` for what that no longer covers.

## Before this file existed

The build sequence through Step 10 and Phase 1 is recorded in
[`docs/PLAN.md`](docs/PLAN.md), and the measured pilot in
[`docs/results`](frontend/content/docs/results.mdx). Briefly: the coordination
substrate, the signed chain, the claim registry, the four arms, the CLI, the
provenance layer, the connectors and the terminal interface, each with its
tests, followed by a 24-run pilot whose every chain verifies offline.
