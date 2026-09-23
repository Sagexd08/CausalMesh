"""Reading causal edges back out of run artifacts (spec §55, §71).

`tasks/runner.py` records a run's edges on `RunResult.edges`, which lands in
the run artifact as `result.edges` — the same place `result.chain` and
`result.outcome` live. This module reads them back the way
`metrics.accounting._read_run` reads costs: straight off the artifact, with
no recomputation, because an edge is either what the run recorded or it is
not evidence at all.

Field names here are load-bearing and easy to get wrong, per
`metrics.accounting`'s own note: the run's edges are at `result.edges`, not
`edges`, and an artifact from before this feature shipped has no `edges` key
at all — read as "no edges recorded" rather than an error, since an older
artifact recording nothing is a fact about when it ran, not a defect in it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import CausalEdge, EdgeValidationError

__all__ = ["EdgeReportError", "RunEdges", "collect_edges", "edges_for_run", "run_edges_to_dict"]


class EdgeReportError(ValueError):
    """A run artifact could not be read, or its edges are malformed."""


@dataclass(frozen=True, slots=True)
class RunEdges:
    """One run's causal edges, with enough identity to report them by."""

    run_id: str
    arm: str
    task_id: str
    edges: tuple[CausalEdge, ...]


def edges_for_run(run_dir: Path) -> RunEdges:
    """Read one run directory's `run.json` and return its edges.

    Raises `EdgeReportError` on a missing or unparsable artifact, or on an
    edge record that fails `CausalEdge.from_dict`'s validation — a
    malformed edge is a located problem to report, not one to skip past
    silently.
    """
    run_dir = Path(run_dir)
    try:
        artifact = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdgeReportError(f"{run_dir}: could not read run.json: {exc}") from exc

    result = artifact.get("result") or {}
    raw_edges = result.get("edges") or ()

    try:
        edges = tuple(CausalEdge.from_dict(record) for record in raw_edges)
    except EdgeValidationError as exc:
        raise EdgeReportError(f"{run_dir}: malformed edge record: {exc}") from exc

    return RunEdges(
        run_id=result.get("run_id") or run_dir.name,
        arm=artifact.get("arm") or result.get("arm") or "?",
        task_id=result.get("task_id") or "?",
        edges=edges,
    )


def collect_edges(experiment_dir: Path) -> list[RunEdges]:
    """Every run's edges in one experiment directory, in run-directory order.

    Runs with no `edges` key, or an empty list, still appear here with an
    empty `edges` tuple — absent means "this run recorded none", which is
    itself the fact a caller asking "which runs have edges" needs to see,
    rather than a row silently missing from the answer.
    """
    experiment_dir = Path(experiment_dir)
    if not experiment_dir.is_dir():
        raise EdgeReportError(f"{experiment_dir} is not a directory")

    run_dirs = sorted(p for p in experiment_dir.iterdir() if (p / "run.json").is_file())
    if not run_dirs:
        raise EdgeReportError(f"{experiment_dir} contains no runs")

    return [edges_for_run(run_dir) for run_dir in run_dirs]


def run_edges_to_dict(run_edges: RunEdges) -> dict[str, Any]:
    return {
        "arm": run_edges.arm,
        "edges": [edge.to_dict() for edge in run_edges.edges],
        "run_id": run_edges.run_id,
        "task_id": run_edges.task_id,
    }
