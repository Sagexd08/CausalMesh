"""`causalmesh serve` — an OpenAI-compatible endpoint that gates and records.

Routes through `server/app.py:create_app` (FastAPI). See `server/app.py`
for the scope decision (gate-and-record, not a full proxy, by default).

`adapters/serve.py` (`ServeConfig`/`run_server`, stdlib `http.server`) was
this command's implementation before the FastAPI migration (Phase 2A).
Nothing in `src/` reaches it anymore -- only its own
`tests/integration/test_serve.py` exercises it. It is left in place rather
than deleted, same as `RunState.TIMED_OUT` and `PathScopedDelivery`
(docs/backlog.md): removing it is a separate, deliberate decision, not a
side effect of this docstring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._output import Exit, fail, note, out_console

app = typer.Typer(help="Run an OpenAI-compatible gate-and-record endpoint.", no_args_is_help=False)


@app.callback(invoke_without_command=True)
def serve_command(
    ctx: typer.Context,
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8420,
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
        str | None, typer.Option("--api-token", envvar="CAUSALMESH_API_TOKEN")
    ] = None,
    dev: Annotated[bool, typer.Option("--dev")] = False,
) -> None:
    """Start the endpoint. Ctrl-C to stop."""
    if ctx.invoked_subcommand is not None:
        return

    try:
        import uvicorn
    except ImportError:
        fail("uvicorn is required: pip install 'causalmesh[server]'")
        raise typer.Exit(Exit.USAGE) from None

    from causalmesh.policy.contract import Contract, ContractError
    from causalmesh.sdk.mesh import CausalMesh
    from causalmesh.server.app import create_app

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

    if dev and host not in ("127.0.0.1", "localhost"):
        fail("--dev mode disables authentication and is only allowed on localhost/127.0.0.1")
        raise typer.Exit(Exit.USAGE)

    if not dev and api_token is None:
        fail("--api-token is required when not in --dev mode")
        raise typer.Exit(Exit.USAGE)

    mesh = CausalMesh(contract=contract, run_id=run_id, agent_id="agent")

    # A token that was given is always enforced, `--dev` or not: `--dev` only
    # permits running without one, it does not switch a supplied one off.
    tokens = {api_token} if api_token else None
    try:
        fastapi_app = create_app(
            mesh=mesh,
            api_tokens=tokens,
            auth_disabled=tokens is None,
            upstream_base_url=upstream,
            upstream_api_key=upstream_api_key,
        )
    except ValueError as exc:
        fail(str(exc), hint="Check --upstream: it must be an http:// or https:// URL.")
        raise typer.Exit(Exit.USAGE) from None

    out_console.print(f"causalmesh serve  [bold]http://{host}:{port}[/bold]  arm={contract.arm}")
    if upstream:
        note(f"forwarding allowed calls to {upstream}")
    else:
        note("no --upstream set; calls are gated and recorded, and get a stub reply")
    note("POST /v1/chat/completions  ·  GET /healthz  ·  Ctrl-C to stop")

    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")
    raise typer.Exit(Exit.OK)
