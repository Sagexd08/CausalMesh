"""The `causalmesh` command line (spec §62).

The entry point declared in `pyproject.toml`. Subcommands live in their own
modules; this file wires them together and owns the global options.

What this CLI is for: making the substrate runnable by someone who has not
read the source. Everything it does was already reachable from Python — the
value here is that the path from `pip install -e .` to a verified chain is
one documented sequence rather than a reading exercise.
"""

from __future__ import annotations

from typing import Annotated

import typer

from causalmesh import __version__
from causalmesh.cli import (
    commands_audit,
    commands_experiment,
    commands_policy,
    commands_serve,
    commands_task,
    commands_verify,
    commands_watch,
)
from causalmesh.cli.commands_agreement import agreement_command
from causalmesh.cli.commands_analyze import analyze_command
from causalmesh.cli.commands_audit import audit_command
from causalmesh.cli.commands_doctor import doctor_command
from causalmesh.cli.commands_policy import init_command
from causalmesh.cli.commands_quickstart import quickstart_command
from causalmesh.cli.commands_watch import watch_command, welcome_command

app = typer.Typer(
    name="causalmesh",
    help=(
        "Coordination you can prove: run agent-fleet experiments and verify "
        "the evidence they produce."
    ),
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"causalmesh {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the installed version and exit.",
        ),
    ] = False,
) -> None:
    """Coordination you can prove: run agent-fleet experiments and verify the evidence."""


app.command("doctor")(doctor_command)
app.command(
    "init",
    help="Write a starter causalmesh.yaml, reading AGENTS.md's Layout table if one exists.",
)(init_command)
app.command(
    "quickstart",
    help="Declare a contract, check the environment, run a smoke collection, verify it. One command.",
)(quickstart_command)
app.add_typer(commands_task.app, name="task")
app.add_typer(commands_experiment.app, name="experiment")
app.command("verify")(commands_verify.verify_command)
app.command("analyze")(analyze_command)
app.command(
    "agreement",
    help="Compute inter-rater kappa (S53) over a judgement file an operator supplies.",
)(agreement_command)
app.add_typer(commands_policy.app, name="policy")
app.add_typer(commands_serve.app, name="serve")
app.add_typer(commands_audit.app, name="manifest")
app.command("audit")(audit_command)
app.command("watch")(watch_command)
app.command("welcome")(welcome_command)
app.add_typer(commands_watch.app, name="connectors")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
