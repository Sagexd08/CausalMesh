# Changelog

Notable changes, newest first. This project is pre-1.0 and follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are
[semantic](https://semver.org/spec/v2.0.0.html) once there is one to break.

An entry here says what changed for someone using the project. What changed
inside it is in the commit log, and what is deliberately absent is in
[`docs/backlog.md`](docs/backlog.md).

## [Unreleased]

## [0.1.0] - 2026-10-12

First public release. Pre-alpha; see `README.md` Status and `docs/backlog.md` for
what is built and what is not.

### Added

- **A content-level merge for contested paths, opt-in** (`contested_merge: three_way` in a
  task file; `--contested-merge three_way` on `scripts/import_cooperbench.py`). Two agents
  that edit different parts of one file now both survive; edits to the same or adjacent
  lines are a conflict, recorded as `RunResult.merge_conflicts` and failing the run. Pure
  Python (`causalmesh.tasks.merge3`), no new dependency. The default is unchanged
  (`last_writer`), so no existing task, hash or result changes. Checked against
  `git merge-file` on all 652 real CooperBench pairs: 98.8% of contested files agree, and
  the pair-level verdict matches CooperBench's own gold report on 97.5%.
  `python scripts/cooperbench_real.py merge-check` reproduces it. Replaying the gold
  patches with it solves 142 of 652 pairs under an offline oracle; nothing about agent
  behaviour is claimed (see `docs/backlog.md`).
- **The section 37 gate says when it could not run.** `check_sensitivity` now checks that
  the task's test command can start in the harness's own environment. A missing test runner
  used to read as NOT SENSITIVE; it is now `COULD NOT RUN` with the reason, and no arm runs.

- **A local CLI demo** (`examples/cli_demo/`): a contract, a gateway that serves one
  tool, an allowed call, a denied call whose handler never runs, and evidence read back
  and verified against the operator's key ring. No key or model needed;
  `python examples/cli_demo/run_demo.py` runs it unattended and the suite runs it too.
  Pre-alpha. Written before `serve --tools`, TLS and `CausalMesh.export` existed, so the
  demo still serves its tool from a short script and holds its evidence in memory.
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
- `AnthropicAdapter`: Anthropic Messages `tool_use` blocks in, `tool_result` blocks out
  (with `is_error`), tool definitions with `input_schema`. No vendor SDK; accepts plain
  dicts or SDK block objects. Sync and async (`handle_tool_use(s)`, `handle_message`, and
  `a`-prefixed twins).
- `LangGraphAdapter`: the LangChain adapter's tools plus `tool_node()`, a real
  `langgraph.prebuilt.ToolNode`. Tested with a real `ToolNode` in a `StateGraph` and a
  prebuilt agent driven by a scripted fake model.
- `CrewAIAdapter`: `crewai.tools.BaseTool` subclasses that route through the gate, sync
  (`_run`) and async (`_arun`). Tested against a fake `BaseTool` only; the real package
  has not been run.
- `BaseFrameworkAdapter.observe` / `aobserve` and `Observation`: the single place a
  model-requested call becomes text, so every adapter classifies errors the same way.
  `bind_arguments` for adapters that receive positional or keyword arguments.
- `tests/integration/test_adapter_gate.py`: one set of safety properties (allowed call
  goes through the gate and is recorded, denied call never reaches the handler, model
  mistakes are answers, unknown agent raises before gate and handler, all on the async
  path too) run through every adapter, plus a check that no adapter module calls a handler.
  No hosted model has driven any adapter.
- **`causalmesh serve --tools MODULE:FUNC | FILE.py:FUNC`** (repeatable): imports the
  operator's code at startup and calls `FUNC(mesh)` to register tools, so `/v1/tools` is
  no longer empty. It runs code with the server's privileges and is never derived from the
  contract or a request. A bad spec stops startup with exit 2.
- **TLS for `serve`:** `--ssl-certfile` and `--ssl-keyfile` (key passphrase only from
  `CAUSALMESH_SSL_KEYFILE_PASSWORD`, checked before the socket opens), and `--require-tls`,
  which refuses a non-loopback bind without them. Without TLS on a non-loopback host `serve`
  warns that tokens cross the network in clear. No mutual TLS and no certificate reload.
- `serve` operability: `X-Request-ID` on every response and log line, an access log with
  no headers or bodies and every configured secret scrubbed, `/readyz`, `--log-level`,
  `--timeout-keep-alive`, `--timeout-graceful-shutdown`; `--workers` above 1 is refused.
- **Token expiry, revocation and rotation for `serve`** without a restart.
  `--agent-token AGENT=TOKEN@EXPIRY`, `--api-token-expires`, and `--tokens-file`
  (YAML or JSON, re-read on change or SIGHUP; `id`, `token`, `agent`, `expires`). A
  credential is valid while `now < expires_at`; past it the request gets 401 "Token
  expired". A bad reload keeps the last good set and logs no content; on POSIX a file
  readable by group or other is refused. Chat and `/execute` events carry `credential_id`,
  the operator's label (never the token or a digest of it), beside `identity_source`.
  `/execute` events record `identity_source` too. The log redactor learns reloaded tokens.
- **`CausalMesh.export(directory)`** writes `run.json` and `keyring.json` (public keys only)
  so `causalmesh verify --run <directory>` verifies an SDK session. `verify` now prefers a
  `keyring.json` beside `run.json` to the keys embedded in the records, fails a run whose
  `keyring.json` is unreadable instead of falling back, and reports which source it used.
  Opt-in `persist_to=<dir>` appends `chain.jsonl` as the session goes.
- **A logical clock in the signed chain.** `ToolGateway` signs `base_us + n * tick_us`
  (`clock_base_us`, `clock_tick_us`), so two sessions with one seed and one call sequence
  share a head hash. The wall-clock time of each call is in the unsigned
  `envelope.wall_time_us_by_event`. (`/v1/chat/completions` was fixed later; see Fixed.)
- `CausalMesh(claims=ClaimRegistry)`: exclusive leases apply to SDK sessions.
  `mesh.claim()`, `mesh.release()`, `mesh.denials()`, `mesh.claim_registry`. Off by default.
  Both default `now_us` to the session's logical time, so a lease expires on the clock the gate reads.
  Same run id for lease and gate.
- `TerminalCheckpointHandler`, a human-attached `CheckpointHandler` (timeout, bounded
  re-prompts, refuse on EOF/closed/no-tty, ASCII-escaped prompts, serialised prompts, own
  decision log); `CausalMesh(checkpoint_handler=...)`; `causalmesh experiment run
  --checkpoint-prompt`. Run artifacts from a run with a handler record its class under
  `provenance`, `reproducible: false` for a non-deterministic one, and `checkpoint_decisions`.
- **Declared totals are reserved, then committed.** `Ledger.reserve` admits callers racing
  on one allowance one at a time, across threads and processes (`BEGIN IMMEDIATE`), and
  `ToolGateway` commits on success and releases on failure. `Tool(spend_on_error=True)`
  counts the amount as spent when the handler raises. A holder that dies leaves its hold
  (fails closed) until `Ledger.release_all`; the reservation exists only on the SDK path.
- **Two more task families:** `interface_consumer` and `shared_utility_refactor`
  (`tasks/*.yaml`, new fixtures), one per section 35 family. Real section 37 verdicts with
  mock agents: both SENSITIVE. The verdicts rest on authored scripts and say nothing about
  agent behaviour.
- **Causal edges:** the integration test result is now a chain event
  (`EventType.INTEGRATION_TEST_RESULT`, identity `integration_test`, payload
  `{command, exit_code, ran}`, no clock), and a `REQUIRED` edge joins the acceptance
  decision to it. `causalmesh analyze --edges` lists counts by relationship kind and each
  edge with labelled endpoints.
- Scheduler: opt-in whole-run watchdog (`--run-timeout`); runs that exceed it reach
  `TIMED_OUT` with partial evidence preserved and a verifiable chain. Cooperative only: a run
  blocked in a synchronous call is not interrupted.
- Scheduler: `RunState.HANDED_OFF` and the `HandoffPackage` record shape, as prerequisites
  for agent handoff on recovery. Not wired into the loop.
- Selectable delivery per run. `policy_for_arm(arm, mode=..., interests=...)` and
  `RunConfig.delivery_mode` choose broadcast or path-scoped delivery for the informed arms.
  Unset behaves as before; C0 stays isolated whatever the mode. `PathScopedDelivery` now has
  a production consumer (the scalability profile).
- `tasks.scaled`, a deterministic generated task for N agents (`ScaledSpec`,
  `generate_scaled_task`); a non-gated `scalability` profile (N in {4, 8, 16}) and
  `causalmesh experiment scalability`, reporting delivered events and coordination bytes for
  broadcast against path-scoped delivery; `metrics.scaling` (`growth_exponent` is `None`
  when undefined). Scripted mock agents only.

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

- **`causalmesh verify --keyring PATH`** is accepted as an alias of `--keys`, and the note
  printed when a chain is checked only against keys embedded in the artifact now says so
  plainly. Exit codes and PASS/FAIL semantics are unchanged.
- **`causalmesh doctor` outside a checkout** reports the missing repository as a warning
  ("not a checkout; the experiment harness is unavailable") rather than a failure, so a
  `pip install` user's first diagnostic no longer exits 1. Real install defects still do.
- **Windows: CooperBench base-file fetches** run git with `core.longpaths`, and the
  integration-test runner resolves `bash` past the WSL relay in `System32` (a relay-only
  `PATH` now reports `COULD NOT RUN` instead of identical arm failures).
- **`/v1/chat/completions` no longer signs the wall clock.** Chat events take the session's
  logical clock and a gateway-counter event id (`sdk_<agent>_<n>`), so two `serve` sessions
  making the same chat calls share a head hash; the wall time is in
  `ToolGateway.wall_times()`, outside the signature.
- **An interrupted collection no longer marks its in-flight run `FAILED`.** Ctrl-C used to
  record a terminal, never-retried failure; the run now stays resumable and finishes on the
  next start.
- **Repaired the `main`-into-`dev` merge** that left the SDK, gateway and `verify` command
  broken (329 failing tests). `persist_to` and `evidence_path` both work and are mutually
  exclusive; `verify` prefers `--keys`, then a `keyring.json` beside `run.json`, then the
  embedded keys.
- `policy/ledger.py` no longer builds SQL with an f-string, and
  `docs/preregistration-draft.md` now says four tasks are plannable (1920 runs), which is
  what the planner produces.
- `LangChainAdapter` tools raised `MissingResourceError` / `ToolNotFoundError` out of the
  caller's loop on a model's bad call; they now return `Action failed: ...`, as the OpenAI
  adapter already did. This is what lets the tools survive inside a LangGraph `ToolNode`.
- `tool_to_json_schema` dropped every parameter when one annotation could not be resolved,
  described `Optional[int]` and `X | None` as `string`, listed `*args` / `**kwargs` as
  required-looking properties, and ignored `Literal` and list item types. `LangChainAdapter`
  handlers with `**kwargs` nested the extras under the parameter name.
- `on: path` (unquoted) under `policy.checkpoints` in `causalmesh.yaml` no longer raises a
  `TypeError` while loading: YAML 1.1 reads an unquoted `on` as a boolean.
- `causalmesh policy show`, `policy check` and `serve` rejected the SDK-only `agent:` and
  `tools:` sections that `policy validate` and `CausalMesh.from_config` accepted. One schema
  now, and an unknown top-level key is still an error everywhere.
- `analyze` reported `total_edges: 0` for a run whose artifact predates edges, a confident
  zero. It is `unknown` (`null` in JSON) now, with `runs_edges_unknown` beside the counts.
- **`causalmesh policy validate` crashed on the SDK sections it is documented to
  check.** Run with no path, it located the file with the strict core loader,
  which rejects `agent:` and `tools:`, so the repository's own
  `examples/causalmesh.yaml` produced a traceback; an invalid contract did too.
  It now finds the file without parsing it and reports errors cleanly. It had no
  tests.
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

- **Manifests no longer record a hostname or username by default.** `machine_id` and
  `operator_id` are a keyed digest (`keyed:` plus 16 hex digits, keyed with a random secret
  kept inside `.git`) or `unknown`. `causalmesh manifest write --record-host` and
  `causalmesh experiment run --record-host` record the real values. A digest compares only
  within one clone. Manifests already in history are untouched.
- `causalmesh experiment plan --profile confirmatory --allow-gated` now plans 1920 runs
  (120 repetitions x 4 arms x 4 tasks), where it planned 960 with two tasks. The gate on the
  profile stays closed and nothing was executed.
- Every run's chain gains one event (`INTEGRATION_TEST_RESULT`), so a `head_hash` stored
  before this change no longer matches a re-run. Two runs of the same arm still agree, and
  older `run.json` artifacts verify as before.
- `profile("scalability")` in the run planner points to `causalmesh experiment scalability`.
  No profile, run count or hash changed.
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
