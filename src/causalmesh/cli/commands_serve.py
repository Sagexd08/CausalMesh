"""`causalmesh serve` — an OpenAI-compatible endpoint that gates and records.

See `adapters/serve.py` for the scope decision (gate-and-record, not a full
proxy, by default).
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

    mesh = CausalMesh(contract=contract, run_id=run_id, agent_id="agent")

    tokens = {api_token} if api_token else None
    fastapi_app = create_app(
        mesh=mesh,
        api_tokens=tokens,
        auth_disabled=dev or api_token is None,
        upstream_base_url=upstream,
        upstream_api_key=upstream_api_key,
    )

    out_console.print(f"causalmesh serve  [bold]http://{host}:{port}[/bold]  arm={contract.arm}")
    if upstream:
        note(f"forwarding allowed calls to {upstream}")
    else:
        note("no --upstream set; calls are gated and recorded, and get a stub reply")
    note("POST /v1/chat/completions  ·  GET /healthz  ·  Ctrl-C to stop")

    if not dev and api_token is None:
        note(
            "WARNING: no --api-token set. Auth is disabled. Use --api-token or set CAUSALMESH_API_TOKEN."
        )

    # In tests, if the user imports serve_command, we don't want to block, but Typer callback runs synchronously.
    # To retain exactly the old test behavior where `run_server` was mockable or used a thread,
    # we might need a workaround for `test_serve.py`. But wait, test_serve.py imports `run_server` from `causalmesh.adapters.serve`.
    # Let's keep `adapters/serve.py` intact and just change the CLI to point to FastAPI.
    # The requirement was: "Do not delete the BaseHTTPRequestHandler implementation immediately. Create a safe migration strategy."
    # So `test_serve.py` which uses `run_server` will still pass!
    # We just update the CLI to use FastAPI instead!

    uvicorn.run(fastapi_app, host=host, port=port, log_level="warning")
    raise typer.Exit(Exit.OK)
