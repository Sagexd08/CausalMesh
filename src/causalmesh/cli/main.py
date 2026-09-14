"""The `causalmesh` command line (spec §62).

The entry point declared in `pyproject.toml`. Subcommands live in their own
modules; this file wires them together and owns the global options.

What this CLI is for: making the substrate runnable by someone who has not
read the source. Everything it does was already reachable from Python — the
value here is that the path from `pip install -e .` to a verified chain is
one documented sequence rather than a reading exercise.
"""

from __future__ import annotations

import typer

from causalmesh.cli import commands_experiment, commands_task, commands_verify
from causalmesh.cli.commands_analyze import analyze_command
from causalmesh.cli.commands_doctor import doctor_command

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

app.command("doctor")(doctor_command)
app.add_typer(commands_task.app, name="task")
app.add_typer(commands_experiment.app, name="experiment")
app.command("verify")(commands_verify.verify_command)
app.command("analyze")(analyze_command)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
