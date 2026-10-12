"""`causalmesh report` -- intervals and tests over a collection (Step 13 primitives, Step 14).

Selects an experiment exactly as `analyze` does, then tabulates it with
Wilson and Newcombe intervals, Fisher exact p-values and a Holm adjustment
across the planned contrasts. The assumptions are the operator's to state:
`--alpha` and `--confidence` are required and `--margin` is optional, with no
default for any of them, because none has been preregistered
(`docs/preregistration-draft.md` is an unsigned draft). Every table is
labelled PILOT or DERIVED; CONFIRMATORY is gated.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail
from causalmesh.cli.commands_analyze import _resolve_experiment


def report_command(
    alpha: Annotated[
        float,
        typer.Option(
            "--alpha", help="Family-wise level for the Holm adjustment. Required, no default."
        ),
    ],
    confidence: Annotated[
        float,
        typer.Option("--confidence", help="Interval level, e.g. 0.95. Required, no default."),
    ],
    margin: Annotated[
        float | None,
        typer.Option(
            "--margin",
            help="Equivalence margin in proportion units (0.10 = 10 points). Omit to skip it.",
        ),
    ] = None,
    experiment_id: Annotated[
        str | None, typer.Option("--id", help="Experiment to report on.")
    ] = None,
    latest: Annotated[
        bool, typer.Option("--latest", help="Report on the most recent experiment.")
    ] = False,
    task_filter: Annotated[str | None, typer.Option("--task", help="Restrict to one task.")] = None,
    baseline_arm: Annotated[
        str, typer.Option("--baseline-arm", help="Arm each other arm is compared against.")
    ] = "C0",
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Report intervals, exact tests and the Holm-adjusted contrasts (PILOT/DERIVED)."""
    from causalmesh.analysis.inference import InferenceError
    from causalmesh.metrics import MetricsError, collect
    from causalmesh.reporting import ReportError, build_report, render_text

    root = root_option.resolve() if root_option else find_root()
    if root is None:
        fail("no CausalMesh checkout found", hint="Run from inside the repository, or pass --root.")
        raise typer.Exit(Exit.USAGE)
    repo = Repo(root)

    experiment_id = _resolve_experiment(repo, experiment_id=experiment_id, latest=latest)

    try:
        metrics = collect(repo.experiment_dir(experiment_id))
    except MetricsError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.ERROR) from exc

    try:
        report = build_report(
            metrics,
            confidence=confidence,
            alpha=alpha,
            margin=margin,
            baseline_arm=baseline_arm,
            task_id=task_filter,
        )
    except (InferenceError, ReportError) as exc:
        fail(str(exc))
        raise typer.Exit(Exit.USAGE) from exc

    # Not `out_console`: Rich would read "[+0.1000, +0.5000]" as a style tag.
    if not emit(report.to_dict(), as_json=as_json):
        typer.echo(render_text(report), nl=False)

    raise typer.Exit(Exit.OK)
