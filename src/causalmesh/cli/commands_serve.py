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
        typer.Option("--upstream", help="Base URL to forward allowed calls to, e.g. https://api.openai.com."),
    ] = None,
    upstream_api_key: Annotated[
        str | None, typer.Option("--upstream-api-key", envvar="CAUSALMESH_UPSTREAM_API_KEY")
    ] = None,
) -> None:
    """Start the endpoint. Ctrl-C to stop."""
    if ctx.invoked_subcommand is not None:
        return

    from causalmesh.adapters.serve import ServeConfig, run_server
    from causalmesh.policy.contract import Contract, ContractError

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

    config = ServeConfig(
        contract=contract,
        run_id=run_id,
        host=host,
        port=port,
        upstream_base_url=upstream,
        upstream_api_key=upstream_api_key,
    )

    out_console.print(f"causalmesh serve  [bold]http://{host}:{port}[/bold]  arm={contract.arm}")
    if upstream:
        note(f"forwarding allowed calls to {upstream}")
    else:
        note("no --upstream set; calls are gated and recorded, and get a stub reply")
    note("POST /v1/chat/completions  ·  GET /healthz  ·  Ctrl-C to stop")

    run_server(config, block=True)
    raise typer.Exit(Exit.OK)
