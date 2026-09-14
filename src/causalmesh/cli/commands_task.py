"""`causalmesh task` — inspect and validate the task suite (spec §36).

Validation here is structural: it checks a task is well-formed and its
fixture exists. Whether the task actually *depends* on coordination is the
§37 sensitivity gate, which costs a real C0-versus-C2 execution to answer
and so is not something a validate command can do.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, out_console, table

app = typer.Typer(help="Inspect and validate tasks.", no_args_is_help=True)


def _repo_or_exit(root_option: Path | None) -> Repo:
    root = root_option.resolve() if root_option else find_root()
    if root is None:
        fail(
            "no CausalMesh checkout found",
            hint="Run from inside the repository, or pass --root.",
        )
        raise typer.Exit(Exit.USAGE)
    return Repo(root)


@app.command("list")
def list_command(
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List the tasks in the suite."""
    from causalmesh.tasks import TaskError, load_tasks

    repo = _repo_or_exit(root_option)
    try:
        tasks = load_tasks(repo.tasks_dir)
    except TaskError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.ERROR) from exc

    payload = [
        {
            "agents": len(task.roles),
            "contested_paths": sorted(task.contested_paths),
            "family": task.family,
            "fixture": task.fixture,
            "hash": task.content_hash(),
            "task_id": task.task_id,
            "version": task.version,
        }
        for task in tasks
    ]
    if not emit(payload, as_json=as_json):
        rendered = table(f"tasks in {repo.tasks_dir}", ["task", "family", "agents", "fixture"])
        for entry in payload:
            rendered.add_row(
                entry["task_id"], entry["family"], str(entry["agents"]), entry["fixture"]
            )
        out_console.print(rendered)
    raise typer.Exit(Exit.OK)


@app.command("validate")
def validate_command(
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate every task in the suite.

    Exits non-zero if any task has an error. Warnings do not fail the
    command: a warning means the task may run, and treating it as a failure
    would make the check useless as a gate.
    """
    from causalmesh.tasks import TaskError, load_tasks, validate_structure

    repo = _repo_or_exit(root_option)
    try:
        tasks = load_tasks(repo.tasks_dir)
    except TaskError as exc:
        fail(str(exc), hint="A malformed task is not skipped — it stops the load.")
        raise typer.Exit(Exit.ERROR) from exc

    reports = [validate_structure(task, fixtures_root=repo.fixtures_dir) for task in tasks]
    invalid = [r for r in reports if not r.valid]

    payload = {
        "invalid": len(invalid),
        "reports": [r.to_dict() for r in reports],
        "tasks": len(reports),
        "valid": all(r.valid for r in reports),
    }
    if not emit(payload, as_json=as_json):
        rendered = table("task validation", ["task", "status", "errors", "warnings"])
        for report in reports:
            status = "[green]VALID[/green]" if report.valid else "[red]INVALID[/red]"
            rendered.add_row(
                report.task_id, status, str(len(report.errors)), str(len(report.warnings))
            )
        out_console.print(rendered)
        for report in reports:
            for issue in report.issues:
                colour = "red" if issue.severity == "error" else "yellow"
                out_console.print(
                    f"  [{colour}]{issue.severity}[/{colour}] {report.task_id}: "
                    f"{issue.code} — {issue.detail}"
                )

    raise typer.Exit(Exit.FAILED if invalid else Exit.OK)
