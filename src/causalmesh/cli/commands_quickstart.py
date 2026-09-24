"""`causalmesh quickstart` -- declare, check, run, verify, in one command.

`welcome` is the interactive first-run screen: it checks the environment,
then lets a person pick one next command from a menu. `policy init`,
`doctor`, `experiment run` and `verify` each do one real thing well, and
composing them by hand is the documented path from a fresh checkout to a
verified chain.

This is the zero-interaction version of that same path, for someone who
wants the whole loop run once rather than picked apart: write a contract if
none exists, confirm the environment can run one, run a smoke collection,
verify what it produced. Each step is the real command underneath --
nothing here reimplements `policy init`, `doctor`, `experiment run` or
`verify`; it calls them, in-process, and stops at the first one that fails
in a way that would make the next step meaningless.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._output import Exit, note, out_console


def _run_step(label: str, callable_: object, **kwargs: object) -> int:
    """Invoke another command's function in-process, and report its exit code.

    Every command in this CLI signals its outcome by raising `typer.Exit`
    (or, for `experiment run`, falling through to an implicit success) --
    that is the same mechanism Typer's own dispatch reacts to, so catching
    it here is calling the command the way the CLI itself does, not a
    parallel invocation path that could drift from what `causalmesh
    <command>` actually does alone.
    """
    out_console.print(f"\n[bold]==> {label}[/bold]")
    try:
        callable_(**kwargs)  # type: ignore[operator]
    except typer.Exit as exc:
        return int(exc.exit_code)
    return int(Exit.OK)


def quickstart_command(
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    profile_name: Annotated[str, typer.Option("--profile")] = "smoke",
    experiment_id_option: Annotated[
        str | None,
        typer.Option(
            "--id",
            help="Experiment id. Defaults to `quickstart_<profile>`; re-running the "
            "same id resumes it, the same as `experiment run`.",
        ),
    ] = None,
    force_init: Annotated[
        bool,
        typer.Option("--force-init", help="Overwrite an existing causalmesh.yaml."),
    ] = False,
) -> None:
    """Declare a contract, check the environment, run a smoke collection,

    verify it. Stops at the first step that fails.
    """
    from causalmesh.cli.commands_doctor import doctor_command
    from causalmesh.cli.commands_experiment import run_command
    from causalmesh.cli.commands_policy import init_command
    from causalmesh.cli.commands_verify import verify_command
    from causalmesh.policy.contract import CONTRACT_FILENAME

    root = (root_option or Path.cwd()).resolve()
    has_contract = (root / CONTRACT_FILENAME).is_file()

    if not has_contract or force_init:
        code = _run_step("causalmesh init", init_command, root_option=root, force=force_init)
        if code != Exit.OK:
            note("quickstart stopped: init did not succeed")
            raise typer.Exit(code)
    else:
        note(
            f"{root / CONTRACT_FILENAME} already exists; skipping init (--force-init to overwrite)"
        )

    code = _run_step("causalmesh doctor", doctor_command, root_option=root)
    if code != Exit.OK:
        note("quickstart stopped: this environment cannot run an experiment yet")
        raise typer.Exit(code)

    experiment_id = experiment_id_option or f"quickstart_{profile_name}"
    code = _run_step(
        f"causalmesh experiment run --profile {profile_name} --id {experiment_id}",
        run_command,
        profile_name=profile_name,
        experiment_id=experiment_id,
        root_option=root,
    )
    if code != Exit.OK:
        note("quickstart stopped: the experiment did not complete cleanly")
        raise typer.Exit(code)

    code = _run_step(
        f"causalmesh verify --id {experiment_id}",
        verify_command,
        experiment_id=experiment_id,
        root_option=root,
    )
    out_console.print()
    if code == Exit.OK:
        note(f"quickstart complete: {experiment_id} ran and verified")
        note(f"read the results with: causalmesh analyze --id {experiment_id}")
    else:
        note("quickstart stopped: the chain did not verify")
    raise typer.Exit(code)
