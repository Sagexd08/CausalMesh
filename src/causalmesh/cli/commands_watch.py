"""`causalmesh watch` and `causalmesh connectors`.

`watch` attaches a live view to a collection. It is read-only by
construction: the run index is opened `mode=ro`, so a monitor can be
attached to a collection already executing in another terminal without any
chance of interfering with it.

`connectors` reports which coding agents and infrastructure this machine
actually has, probed rather than assumed.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table

app = typer.Typer(help="Inspect the agents and infrastructure on this machine.", no_args_is_help=True)

# Fast enough to feel live, slow enough that a monitor costs nothing next to
# the run it is watching.
REFRESH_HZ = 4


def _repo_or_exit(root_option: Path | None) -> Repo:
    root = root_option.resolve() if root_option else find_root()
    if root is None:
        fail("no CausalMesh checkout found", hint="Run from inside the repository, or pass --root.")
        raise typer.Exit(Exit.USAGE)
    return Repo(root)


def watch_command(
    experiment_id: Annotated[str | None, typer.Option("--id", help="Collection to watch.")] = None,
    latest: Annotated[bool, typer.Option("--latest", help="Watch the most recent collection.")] = False,
    once: Annotated[
        bool, typer.Option("--once", help="Render a single frame and exit.")
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
) -> None:
    """Watch a collection execute, live."""
    from rich.live import Live

    from causalmesh.tui import read_snapshot, render

    repo = _repo_or_exit(root_option)
    available = repo.experiments()
    if not available:
        fail("no experiments found", hint="Run `causalmesh experiment run` first.")
        raise typer.Exit(Exit.FAILED)

    if experiment_id is None:
        if not latest:
            fail("nothing selected", hint=f"Pass --latest or --id. Available: {', '.join(available)}")
            raise typer.Exit(Exit.USAGE)
        experiment_id = available[0]
    elif experiment_id not in available:
        fail(f"unknown experiment {experiment_id!r}", hint=f"Available: {', '.join(available)}")
        raise typer.Exit(Exit.USAGE)

    directory = repo.experiment_dir(experiment_id)
    started = time.monotonic()

    if once:
        out_console.print(render(read_snapshot(directory, started_at=started)))
        raise typer.Exit(Exit.OK)

    try:
        with Live(
            render(read_snapshot(directory, started_at=started)),
            console=out_console,
            refresh_per_second=REFRESH_HZ,
            screen=False,
        ) as live:
            while True:
                snapshot = read_snapshot(directory, started_at=started)
                live.update(render(snapshot))
                # Stop when the collection is done rather than spinning
                # forever: a watcher left running on a finished collection
                # is a process the operator has to remember to kill.
                if snapshot.total and snapshot.finished >= snapshot.total:
                    break
                time.sleep(1 / REFRESH_HZ)
    except KeyboardInterrupt:
        note("stopped watching; the collection is unaffected")
        raise typer.Exit(Exit.OK) from None

    raise typer.Exit(Exit.OK)


@app.command("list")
def connectors_command(
    agents_only: Annotated[
        bool, typer.Option("--agents", help="Only probe coding agents.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Probe this machine for coding agents and infrastructure."""
    from causalmesh.connectors.discovery import AGENT_SPECS, discover
    from causalmesh.connectors.process import SPECS

    probes = discover(AGENT_SPECS if agents_only else None)
    payload = {
        "drivable": sorted(SPECS),
        "probes": [probe.to_dict() for probe in probes],
        "usable": sum(1 for probe in probes if probe.usable),
    }

    if not emit(payload, as_json=as_json):
        rendered = table(
            "this machine", ["tool", "kind", "status", "version", "drivable", "detail"]
        )
        for probe in probes:
            colour = {
                "available": "green",
                "degraded": "yellow",
                "absent": "red",
            }[probe.availability.value]
            drivable = "yes" if probe.name in SPECS and probe.usable else "-"
            rendered.add_row(
                probe.name,
                probe.kind,
                f"[{colour}]{probe.availability.value}[/{colour}]",
                probe.version or "-",
                drivable,
                probe.detail[:44],
            )
        out_console.print(rendered)
        note(
            "drivable means this build has an exercised headless interface for it; "
            f"currently {', '.join(sorted(SPECS))}"
        )
        note("a real agent is nondeterministic and costs money per run")

    raise typer.Exit(Exit.OK)
