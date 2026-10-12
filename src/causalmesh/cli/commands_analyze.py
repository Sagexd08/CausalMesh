"""`causalmesh analyze` — read a collection's costs and contrasts (§44, §46).

Descriptive only. The command reports what the runs did; it makes no claim
that any difference is distinguishable from noise; intervals and exact tests
are `causalmesh report`'s. Every table it prints is labelled PILOT or
DERIVED in the §68 sense rather than presented as a result.

The per-task view is the default for the contrasts because the pooled one
is actively misleading on this design: enforcement costs nothing on a task
with disjoint ownership and every success on a contested one, and the mean
of those two describes neither.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

from causalmesh.cli._context import Repo, find_root
from causalmesh.cli._output import Exit, emit, fail, note, out_console, table


def _fmt(value: float | None, *, places: int = 0, sign: bool = False) -> str:
    if value is None:
        return "-"
    formatted = f"{value:+.{places}f}" if sign else f"{value:.{places}f}"
    return formatted


def _rate(value: float | None) -> str:
    return "-" if value is None else f"{value:.0%}"


def _resolve_experiment(repo: Repo, *, experiment_id: str | None, latest: bool) -> str:
    available = repo.experiments()
    if not available:
        fail("no experiments found", hint="Run `causalmesh experiment run` first.")
        raise typer.Exit(Exit.FAILED)
    if experiment_id is None:
        if not latest:
            fail(
                "nothing selected", hint=f"Pass --latest or --id. Available: {', '.join(available)}"
            )
            raise typer.Exit(Exit.USAGE)
        return available[0]
    if experiment_id not in available:
        fail(f"unknown experiment {experiment_id!r}", hint=f"Available: {', '.join(available)}")
        raise typer.Exit(Exit.USAGE)
    return experiment_id


def _count_cell(value: int | None) -> str:
    """A count, or `unknown` when nothing it counted was recorded."""
    return "unknown" if value is None else str(value)


def _analyze_edges(repo: Repo, experiment_id: str, *, as_json: bool) -> None:
    """`causalmesh analyze --edges`: the causal edges a collection recorded.

    Reads `result.edges` straight out of each run artifact (see
    `causalmesh.edges.report`) rather than through the cost-accounting path
    above -- an edge is evidence about relationships between events, not a
    cost, and routing it through `RunMetrics` would stretch that type to
    carry something outside its stated scope.

    A run whose artifact has no `edges` key predates edges. It is reported
    as `unknown`, never as zero, and it is left out of every count rather
    than contributing a 0 to it. Descriptive only, like the rest of this
    command: per-edge rows are PILOT (what the pilot's runs recorded), the
    counts over them are DERIVED.
    """
    from causalmesh.edges import (
        EdgeReportError,
        collect_edges,
        count_by_relationship,
        run_edges_to_dict,
        total_edges,
    )

    try:
        runs = collect_edges(repo.experiment_dir(experiment_id))
    except EdgeReportError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.ERROR) from exc

    known = [run for run in runs if run.recorded]
    unknown_count = len(runs) - len(known)
    by_relationship = count_by_relationship(runs)
    total = total_edges(runs)
    payload = {
        "by_relationship": by_relationship,
        "experiment_id": experiment_id,
        "label": "PILOT",
        "runs": [run_edges_to_dict(run) for run in runs],
        "runs_edges_unknown": unknown_count,
        "runs_with_edges": sum(1 for run in known if run.edges) if known else None,
        "total_edges": total,
        "total_runs": len(runs),
    }

    if not emit(payload, as_json=as_json):
        counts = table(f"{experiment_id} - causal edges by kind  [DERIVED]", ["kind", "edges"])
        if by_relationship is None:
            counts.add_row("unknown", "unknown")
        else:
            for kind, count in by_relationship.items():
                counts.add_row(kind, str(count))
        out_console.print(counts)

        rendered = table(
            f"{experiment_id} - causal edges  [PILOT]",
            ["run", "arm", "task", "kind", "from (effect)", "to (cause)"],
        )
        for run in known:
            for edge in run.edges:
                rendered.add_row(
                    escape(run.run_id),
                    escape(run.arm),
                    escape(run.task_id),
                    str(edge.relationship),
                    escape(f"{edge.from_event_id}\n{run.label_for(edge.from_event_id)}"),
                    escape(f"{edge.to_event_id}\n{run.label_for(edge.to_event_id)}"),
                )
        out_console.print(rendered)

        if unknown_count:
            note(
                f"{unknown_count} of {len(runs)} run(s) predate edges: their edges are "
                "unknown, not zero, and are left out of every count above"
            )
        if known and total == 0:
            note("no edges recorded by the runs that record them")
        note(
            f"{_count_cell(total)} edge(s) across {len(known)} run(s) that record edges; "
            "labels come from each artifact's chain and read unknown where it has none"
        )
        note("descriptive only: edges are recorded relationships, not a causal estimate")

    raise typer.Exit(Exit.OK)


def analyze_command(
    experiment_id: Annotated[
        str | None, typer.Option("--id", help="Experiment to analyze.")
    ] = None,
    latest: Annotated[
        bool, typer.Option("--latest", help="Analyze the most recent experiment.")
    ] = False,
    task_filter: Annotated[str | None, typer.Option("--task", help="Restrict to one task.")] = None,
    pooled: Annotated[
        bool, typer.Option("--pooled", help="Also show contrasts pooled across tasks.")
    ] = False,
    edges: Annotated[
        bool,
        typer.Option("--edges", help="Show causal edges recorded by this collection instead."),
    ] = False,
    root_option: Annotated[Path | None, typer.Option("--root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Report per-arm costs and the four planned contrasts."""
    from causalmesh.metrics import MetricsError, collect, measure

    root = root_option.resolve() if root_option else find_root()
    if root is None:
        fail("no CausalMesh checkout found", hint="Run from inside the repository, or pass --root.")
        raise typer.Exit(Exit.USAGE)
    repo = Repo(root)

    experiment_id = _resolve_experiment(repo, experiment_id=experiment_id, latest=latest)

    if edges:
        _analyze_edges(repo, experiment_id, as_json=as_json)
        return

    try:
        metrics = collect(repo.experiment_dir(experiment_id))
    except MetricsError as exc:
        fail(str(exc))
        raise typer.Exit(Exit.ERROR) from exc

    if task_filter is not None and task_filter not in metrics.task_ids:
        fail(
            f"unknown task {task_filter!r}",
            hint=f"This collection ran: {', '.join(metrics.task_ids)}",
        )
        raise typer.Exit(Exit.USAGE)

    tasks = [task_filter] if task_filter else metrics.task_ids
    payload = {
        "arms": {arm_id: arm.to_dict() for arm_id, arm in sorted(metrics.arms.items())},
        "balanced": metrics.is_balanced(),
        "contrasts_by_task": {
            task: [result.to_dict() for result in measure(metrics, task_id=task)] for task in tasks
        },
        "experiment_id": metrics.experiment_id,
        "label": "PILOT",
        "pooled_contrasts": [result.to_dict() for result in measure(metrics)],
        "runs": metrics.run_count,
        "tasks": metrics.task_ids,
    }

    if not emit(payload, as_json=as_json):
        cost = table(
            f"{metrics.experiment_id} - cost and outcome by arm  [PILOT]",
            [
                "arm",
                "runs",
                "passed",
                "success",
                "bytes/run",
                "tokens/run",
                "bytes/turn",
                "denials",
            ],
        )
        for arm_id, arm in sorted(metrics.arms.items()):
            cost.add_row(
                arm_id,
                str(arm.run_count),
                f"{arm.successes}/{len(arm.known_outcomes)}",
                _rate(arm.success_rate),
                _fmt(arm.mean_coordination_bytes),
                _fmt(arm.mean_coordination_tokens),
                _fmt(arm.bytes_per_turn, places=1),
                str(arm.denials),
            )
        out_console.print(cost)
        if not metrics.is_balanced():
            note("this collection is unbalanced; contrasts across it are weaker than they look")

        for task in tasks:
            rendered = table(
                f"contrasts - {task}  [DERIVED]",
                ["contrast", "comparison", "isolates", "success delta", "cost ratio"],
            )
            for result in measure(metrics, task_id=task):
                rendered.add_row(
                    result.name.replace("_", " "),
                    f"{result.baseline} -> {result.treatment}",
                    result.isolates,
                    _fmt(result.success_delta, places=2, sign=True),
                    "-" if result.bytes_ratio is None else f"{result.bytes_ratio:.3f}x",
                )
            out_console.print(rendered)

        if pooled:
            rendered = table(
                "contrasts - pooled across tasks  [DERIVED]",
                ["contrast", "comparison", "success delta", "cost ratio"],
            )
            for result in measure(metrics):
                rendered.add_row(
                    result.name.replace("_", " "),
                    f"{result.baseline} -> {result.treatment}",
                    _fmt(result.success_delta, places=2, sign=True),
                    "-" if result.bytes_ratio is None else f"{result.bytes_ratio:.3f}x",
                )
            out_console.print(rendered)
            note("pooled figures average across tasks whose enforcement behaviour differs")

        note("descriptive only: no interval, no significance test; see `causalmesh report`")

    raise typer.Exit(Exit.OK)
