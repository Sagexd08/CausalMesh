"""`causalmesh serve` — an OpenAI-compatible endpoint that gates and records.

Routes through `server/app.py:create_app` (FastAPI). See `server/app.py`
for the scope decision (gate-and-record, not a full proxy, by default).

A stdlib `http.server` implementation of this command (`adapters/serve.py`)
existed before the FastAPI migration. It was removed on 2026-09-30: nothing
reached it, it had no authentication, and it still carried defects fixed here.
"""

from __future__ import annotations

import signal
import time
from pathlib import Path
from typing import Annotated, Any

import typer

from causalmesh.cli._output import Exit, fail, note, out_console, warn

app = typer.Typer(help="Run an OpenAI-compatible gate-and-record endpoint.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def serve_command(
    ctx: typer.Context,
    host: Annotated[str, typer.Option("--host", envvar="CAUSALMESH_HOST")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", envvar="CAUSALMESH_PORT")] = 8420,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    run_id: Annotated[str, typer.Option("--run-id")] = "serve",
    upstream: Annotated[
        str | None,
        typer.Option(
            "--upstream", help="Base URL to forward allowed calls to, e.g. https://api.openai.com."
        ),
    ] = None,
    upstream_api_key: Annotated[
        str | None, typer.Option("--upstream-api-key", envvar="CAUSALMESH_UPSTREAM_API_KEY")
    ] = None,
    api_token: Annotated[
        str | None,
        typer.Option(
            "--api-token",
            envvar="CAUSALMESH_API_TOKEN",
            help="A token any client may use, naming any agent it likes (asserted, not proven).",
        ),
    ] = None,
    api_token_expires: Annotated[
        str | None,
        typer.Option(
            "--api-token-expires",
            envvar="CAUSALMESH_API_TOKEN_EXPIRES",
            help="When --api-token stops working: ISO 8601 (2026-12-31T00:00:00Z) or unix seconds.",
        ),
    ] = None,
    agent_token: Annotated[
        list[str] | None,
        typer.Option(
            "--agent-token",
            envvar="CAUSALMESH_AGENT_TOKENS",
            help=(
                "AGENT=TOKEN[@EXPIRY], repeatable. A token bound to one agent: the server "
                "takes the agent from the token and refuses a request that names another. "
                "EXPIRY is ISO 8601 (2026-12-31T00:00:00Z) or unix seconds; after it the "
                "token gets 401. Use --tokens-file for a token that itself ends in @ and a date."
            ),
        ),
    ] = None,
    tokens_file: Annotated[
        Path | None,
        typer.Option(
            "--tokens-file",
            envvar="CAUSALMESH_TOKENS_FILE",
            help=(
                "YAML or JSON file of credentials (id, token, agent, expires), re-read when it "
                "changes or on SIGHUP (POSIX), so a token can be revoked, added or rotated "
                "without a restart. A bad edit keeps the last good set. On POSIX it must not "
                "be accessible to group or other (chmod 600). See docs/security.md."
            ),
        ),
    ] = None,
    max_body_bytes: Annotated[
        int,
        typer.Option("--max-body-bytes", help="Refuse request bodies larger than this (413)."),
    ] = 1_048_576,
    rate_limit: Annotated[
        int | None,
        typer.Option(
            "--rate-limit",
            help="Requests per minute allowed per credential, in this process (429 beyond it).",
        ),
    ] = None,
    ssl_certfile: Annotated[
        Path | None,
        typer.Option(
            "--ssl-certfile",
            envvar="CAUSALMESH_SSL_CERTFILE",
            help="PEM certificate (chain) to serve HTTPS with. Needs --ssl-keyfile.",
        ),
    ] = None,
    ssl_keyfile: Annotated[
        Path | None,
        typer.Option(
            "--ssl-keyfile",
            envvar="CAUSALMESH_SSL_KEYFILE",
            help=(
                "PEM private key. If it is encrypted, put its passphrase in the environment "
                "variable CAUSALMESH_SSL_KEYFILE_PASSWORD (never on the command line)."
            ),
        ),
    ] = None,
    require_tls: Annotated[
        bool,
        typer.Option(
            "--require-tls",
            envvar="CAUSALMESH_REQUIRE_TLS",
            help="Refuse to start on a non-localhost host without --ssl-certfile/--ssl-keyfile.",
        ),
    ] = False,
    tools: Annotated[
        list[str] | None,
        typer.Option(
            "--tools",
            help=(
                "MODULE:FUNC or FILE.py:FUNC, repeatable. FUNC(mesh) registers tools with "
                "mesh.register_tool. This IMPORTS AND RUNS operator code at startup, with "
                "the server's privileges; only name code you would deploy."
            ),
        ),
    ] = None,
    workers: Annotated[
        int,
        typer.Option(
            "--workers",
            help="Only 1 is supported: evidence and the chain are per process, calls are serial.",
        ),
    ] = 1,
    timeout_keep_alive: Annotated[
        int,
        typer.Option("--timeout-keep-alive", help="Seconds an idle keep-alive connection is held."),
    ] = 5,
    timeout_graceful_shutdown: Annotated[
        int,
        typer.Option(
            "--timeout-graceful-shutdown",
            help="Seconds to let in-flight requests finish after SIGINT/SIGTERM before closing.",
        ),
    ] = 10,
    log_level: Annotated[
        str, typer.Option("--log-level", help="debug, info, warning, error or critical.")
    ] = "info",
    dev: Annotated[bool, typer.Option("--dev")] = False,
) -> None:
    """Start the endpoint. Ctrl-C to stop."""
    if ctx.invoked_subcommand is not None:
        return

    if workers != 1:
        fail(
            f"--workers {workers} is not supported",
            hint=(
                "Each worker process would hold its own evidence chain and its own rate "
                "limits, and tool calls are serialised by design. Run one process."
            ),
        )
        raise typer.Exit(Exit.USAGE)
    if log_level.lower() not in ("debug", "info", "warning", "error", "critical"):
        fail(f"--log-level {log_level!r} is not one of debug, info, warning, error, critical")
        raise typer.Exit(Exit.USAGE)
    if timeout_keep_alive < 1 or timeout_graceful_shutdown < 1:
        fail("--timeout-keep-alive and --timeout-graceful-shutdown must be at least 1 second")
        raise typer.Exit(Exit.USAGE)

    try:
        import uvicorn
    except ImportError:
        fail("uvicorn is required: pip install 'causalmesh[server]'")
        raise typer.Exit(Exit.USAGE) from None

    from causalmesh.policy.contract import Contract, ContractError
    from causalmesh.sdk.config import load_sdk_config
    from causalmesh.sdk.errors import ConfigurationError
    from causalmesh.sdk.mesh import CausalMesh
    from causalmesh.server.app import create_app
    from causalmesh.server.credentials import (
        Credential,
        agent_token_label,
        parse_expiry,
        split_token_expiry,
    )
    from causalmesh.server.observability import configure_logging
    from causalmesh.server.tls import TlsConfigError, is_loopback, key_password, validate_tls
    from causalmesh.server.tools import ToolLoadError, load_tools

    try:
        contract = Contract.find(root_option or Path.cwd())
    except ContractError as exc:
        fail(str(exc), hint="Fix causalmesh.yaml, then run this again.")
        raise typer.Exit(Exit.USAGE) from None
    if contract is None:
        fail(
            "no causalmesh.yaml found",
            hint="Run `causalmesh policy init` to write one, or pass --root.",
        )
        raise typer.Exit(Exit.USAGE)

    # An empty token (`--api-token "$UNSET_VAR"`) is no token: passing it on
    # would leave the server with no valid tokens and authentication off.
    if api_token is not None and not api_token.strip():
        api_token = None

    if dev and not is_loopback(host):
        fail("--dev mode disables authentication and is only allowed on localhost/127.0.0.1")
        raise typer.Exit(Exit.USAGE)

    # Tokens with no expiry go through `create_app`'s plain arguments exactly
    # as before; one with an expiry is a labelled `Credential` (`agent-token:NAME`,
    # `api-token`: stable, from configuration, never from the secret).
    bound: dict[str, str] = {}
    expiring: list[Credential] = []
    seen_agents: set[str] = set()
    now = time.time()
    for pair in agent_token or []:
        agent, separator, secret = pair.partition("=")
        if not separator or not agent.strip() or not secret.strip():
            fail(
                "--agent-token must look like AGENT=TOKEN, with both parts non-blank",
                hint="For example: --agent-token coder=s3cret-value",
            )
            raise typer.Exit(Exit.USAGE)
        if agent in seen_agents:
            fail(f"--agent-token names {agent!r} twice")
            raise typer.Exit(Exit.USAGE)
        seen_agents.add(agent)
        try:
            secret, expires_at = split_token_expiry(secret)
        except ValueError as exc:
            fail(f"--agent-token for {agent!r}: {exc}")
            raise typer.Exit(Exit.USAGE) from None
        if expires_at is None:
            bound[agent] = secret
            continue
        if expires_at <= now:
            fail(f"--agent-token for {agent!r} is already expired")
            raise typer.Exit(Exit.USAGE)
        try:
            expiring.append(Credential(agent_token_label(agent), secret, agent, expires_at))
        except ValueError as exc:
            fail(str(exc))
            raise typer.Exit(Exit.USAGE) from None

    if api_token_expires is not None:
        if api_token is None:
            fail("--api-token-expires needs --api-token")
            raise typer.Exit(Exit.USAGE)
        try:
            api_expires_at = parse_expiry(api_token_expires)
        except ValueError as exc:
            fail(f"--api-token-expires: {exc}")
            raise typer.Exit(Exit.USAGE) from None
        if api_expires_at <= now:
            fail("--api-token is already expired (--api-token-expires is in the past)")
            raise typer.Exit(Exit.USAGE)
        expiring.append(Credential("api-token", api_token, None, api_expires_at))
        api_token = None
        expiring_api = True
    else:
        expiring_api = False

    if tokens_file is not None and not tokens_file.is_file():
        fail(f"--tokens-file {tokens_file} is not a file")
        raise typer.Exit(Exit.USAGE)

    authenticated = bool(api_token or expiring_api or bound or expiring or tokens_file)
    if not dev and not authenticated:
        fail(
            "a token is required when not in --dev mode: --api-token, --agent-token, --tokens-file"
        )
        raise typer.Exit(Exit.USAGE)

    passphrase = key_password()
    try:
        tls_on = validate_tls(ssl_certfile, ssl_keyfile, passphrase)
    except TlsConfigError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.USAGE) from None

    if not tls_on and not is_loopback(host):
        if require_tls:
            fail(
                f"--require-tls: refusing to serve on {host} without TLS",
                hint="Pass --ssl-certfile and --ssl-keyfile, or bind to 127.0.0.1.",
            )
            raise typer.Exit(Exit.USAGE)
        warn(
            f"serving bearer tokens over plain HTTP on {host}: anyone on the network path can "
            "read them. Use --ssl-certfile/--ssl-keyfile, or terminate TLS in a reverse proxy "
            "and keep this port private. --require-tls turns this warning into a refusal."
        )

    # The default agent is the contract's `agent.id` when it names one, so the
    # file means the same thing here as in `CausalMesh.from_config`.
    default_agent = "agent"
    if contract.source is not None:
        try:
            default_agent = load_sdk_config(contract.source)[1].agent_id or default_agent
        except ConfigurationError as exc:
            fail(str(exc), hint="Fix causalmesh.yaml, then run this again.")
            raise typer.Exit(Exit.USAGE) from None

    mesh = CausalMesh(contract=contract, run_id=run_id, agent_id=default_agent)

    # Imports and runs operator code, by explicit request only (server/tools.py).
    loaded: list[str] = []
    for index, spec in enumerate(tools or []):
        try:
            loaded.extend(load_tools(mesh, spec, index=index))
        except ToolLoadError as exc:
            fail(str(exc), hint="See `causalmesh serve --help` for the --tools forms.")
            raise typer.Exit(Exit.USAGE) from None

    # A token that was given is always enforced, `--dev` or not: `--dev` only
    # permits running without one, it does not switch a supplied one off.
    tokens = {api_token} if api_token else None
    try:
        fastapi_app = create_app(
            mesh=mesh,
            api_tokens=tokens,
            agent_tokens=bound or None,
            credentials=expiring or None,
            tokens_file=tokens_file,
            auth_disabled=not authenticated,
            upstream_base_url=upstream,
            upstream_api_key=upstream_api_key,
            max_body_bytes=max_body_bytes,
            rate_limit_per_minute=rate_limit,
        )
    except ValueError as exc:
        fail(
            str(exc),
            hint="Check --upstream (an http:// or https:// URL), --agent-token and --tokens-file.",
        )
        raise typer.Exit(Exit.USAGE) from None

    store = fastapi_app.state.credentials
    if any(len(secret) < 16 for secret in store.secrets()):
        note(
            "a token shorter than 16 characters can be guessed; use a long random one "
            '(for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`)'
        )

    scheme = "https" if tls_on else "http"
    out_console.print(
        f"causalmesh serve  [bold]{scheme}://{host}:{port}[/bold]  arm={contract.arm}"
    )
    if loaded:
        note(f"tools loaded by --tools: {', '.join(sorted(loaded))}")
    if tokens_file is not None:
        reload_hint = "on change or SIGHUP" if hasattr(signal, "SIGHUP") else "on change"
        note(f"credentials are re-read from {tokens_file} ({reload_hint}); a bad edit is ignored")
    if upstream:
        note(f"forwarding allowed calls to {upstream}")
    else:
        note("no --upstream set; calls are gated and recorded, and get a stub reply")
    note("POST /v1/chat/completions, /v1/tools/NAME/execute  |  GET /health, /readyz  |  Ctrl-C")
    note("evidence is held in this process only; it is gone when the server stops")

    # Access logging is ours (method, path, status: never headers or bodies),
    # so uvicorn's is off. Every configured secret is scrubbed from what is written.
    # The credential store is asked on every record, so a token added by a
    # reload is scrubbed from the next line, and a revoked one stays scrubbed.
    restore_logging = configure_logging(
        level=log_level,
        secrets=lambda: [*store.secrets(), upstream_api_key or "", passphrase or ""],
    )
    # SIGHUP asks for a re-read on the next request. Only set when there is a
    # file to re-read, so the default action (terminate) is otherwise untouched.
    restore_sighup = None
    if tokens_file is not None and hasattr(signal, "SIGHUP"):
        try:
            previous_handler = signal.signal(signal.SIGHUP, lambda *_: store.request_reload())
            restore_sighup = (signal.SIGHUP, previous_handler)
        except ValueError:  # not the main thread: the mtime check still works
            pass
    ssl_options: dict[str, Any] = {}
    if tls_on:
        ssl_options = {
            "ssl_certfile": str(ssl_certfile),
            "ssl_keyfile": str(ssl_keyfile),
            "ssl_keyfile_password": passphrase,
        }
    try:
        uvicorn.run(
            fastapi_app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            timeout_keep_alive=timeout_keep_alive,
            timeout_graceful_shutdown=timeout_graceful_shutdown,
            **ssl_options,
        )
    finally:
        if restore_sighup is not None:
            signal.signal(*restore_sighup)
        restore_logging()
    raise typer.Exit(Exit.OK)
