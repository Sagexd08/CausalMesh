"""Reading causal edges back out of run artifacts (spec §55, §71).

`tasks/runner.py` records a run's edges on `RunResult.edges`, which lands in
the run artifact as `result.edges` — the same place `result.chain` and
`result.outcome` live. This module reads them back the way
`metrics.accounting._read_run` reads costs: straight off the artifact, with
no recomputation, because an edge is either what the run recorded or it is
not evidence at all.

Field names here are load-bearing and easy to get wrong, per
`metrics.accounting`'s own note: the run's edges are at `result.edges`, not
`edges`.

An artifact from before edges shipped has no `edges` key at all. That is
reported as **unknown**, never as zero: an older artifact recording nothing
is a fact about when it ran, and "this run had no relationships" is a claim
it cannot support. A run that has the key with an empty list recorded a real
zero. `RunEdges.recorded` keeps the two apart, and every count built on top
of it (`count_by_relationship`, `total_edges`) returns `None` rather than a
confident 0 when nothing it counted was recorded.

Edge endpoints are opaque event ids. Where the artifact also carries the
run's chain (`artifact["chain"]`), `RunEdges.label_for` resolves an id to a
short description of the event it names ("FAILURE by agent_b, denied"), and
says `unresolved` for an id the chain does not contain. Without a chain the
label is `unknown`: nothing was checked, so nothing can be said.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .types import CausalEdge, EdgeValidationError, RelationshipType

__all__ = [
    "UNKNOWN",
    "UNRESOLVED",
    "EdgeReportError",
    "RunEdges",
    "collect_edges",
    "count_by_relationship",
    "edges_for_run",
    "run_edges_to_dict",
    "total_edges",
]

UNKNOWN = "unknown"
UNRESOLVED = "unresolved"


class EdgeReportError(ValueError):
    """A run artifact could not be read, or its edges are malformed."""


@dataclass(frozen=True, slots=True)
class RunEdges:
    """One run's causal edges, with enough identity to report them by.

    `recorded` is False when the artifact has no `result.edges` key, i.e. it
    predates edges; `edges` is then empty but that emptiness means
    "unknown", not "none".

    `event_labels` maps event id to a short description, built from the
    artifact's chain; `chain_present` says whether there was a chain to
    build it from, which is what separates `unknown` from `unresolved`.
    """

    run_id: str
    arm: str
    task_id: str
    edges: tuple[CausalEdge, ...]
    recorded: bool = True
    chain_present: bool = False
    event_labels: Mapping[str, str] = field(default_factory=dict, compare=False)

    def label_for(self, event_id: str) -> str:
        if not self.chain_present:
            return UNKNOWN
        return self.event_labels.get(event_id, UNRESOLVED)


def _ascii(text: str) -> str:
    """Terminal output is ASCII (AGENTS.md); escape rather than drop."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _describe_event(event: Mapping[str, Any]) -> str:
    """A short, ASCII label for one chain event.

    Built only from fields that are already on the event; a field that is
    absent is omitted or shown as `unknown`, never defaulted to something
    that looks like a value.
    """
    event_type = str(event.get("event_type") or UNKNOWN)
    identity = event.get("identity") or {}
    actor = identity.get("agent_id") if isinstance(identity, Mapping) else None
    payload = event.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}

    detail = ""
    if event_type == "FAILURE":
        outcome = payload.get("outcome")
        detail = str(outcome) if outcome is not None else ""
    elif event_type == "POLICY_VERDICT":
        allowed = payload.get("allowed")
        verdict = (
            UNKNOWN if not isinstance(allowed, bool) else ("allowed" if allowed else "refused")
        )
        rule = payload.get("rule")
        detail = f"{verdict}, rule {rule}" if rule else verdict
    elif event_type == "ACCEPTANCE_DECIDED":
        verdict_value = payload.get("verdict")
        detail = str(verdict_value) if verdict_value is not None else UNKNOWN
    elif event_type == "INTEGRATION_TEST_RESULT":
        exit_code = payload.get("exit_code")
        detail = f"exit code {exit_code if exit_code is not None else UNKNOWN}"

    label = f"{event_type} by {actor if actor else UNKNOWN}"
    if detail:
        label = f"{label}, {detail}"
    return _ascii(label)


def _event_labels(chain: object) -> tuple[bool, dict[str, str]]:
    """(chain present, event id -> label) from an artifact's `chain` value."""
    if not isinstance(chain, list) or not chain:
        return False, {}
    labels: dict[str, str] = {}
    for record in chain:
        event = record.get("event") if isinstance(record, Mapping) else None
        if not isinstance(event, Mapping):
            continue
        event_id = event.get("event_id")
        if isinstance(event_id, str):
            labels[event_id] = _describe_event(event)
    return True, labels


def edges_for_run(run_dir: Path) -> RunEdges:
    """Read one run directory's `run.json` and return its edges.

    Raises `EdgeReportError` on a missing or unparsable artifact, on an
    `edges` value that is not a list, or on an edge record that fails
    `CausalEdge.from_dict`'s validation — a malformed edge is a located
    problem to report, not one to skip past silently.
    """
    run_dir = Path(run_dir)
    try:
        artifact = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdgeReportError(f"{run_dir}: could not read run.json: {exc}") from exc

    result = artifact.get("result") or {}
    recorded = "edges" in result
    raw_edges = result.get("edges") if recorded else ()
    if raw_edges is None:
        raw_edges = ()
    if not isinstance(raw_edges, list | tuple):
        raise EdgeReportError(f"{run_dir}: result.edges must be a list, got {raw_edges!r}")

    try:
        edges = tuple(CausalEdge.from_dict(record) for record in raw_edges)
    except EdgeValidationError as exc:
        raise EdgeReportError(f"{run_dir}: malformed edge record: {exc}") from exc

    chain_present, labels = _event_labels(artifact.get("chain"))

    return RunEdges(
        run_id=result.get("run_id") or run_dir.name,
        arm=artifact.get("arm") or result.get("arm") or "?",
        task_id=result.get("task_id") or "?",
        edges=edges,
        recorded=recorded,
        chain_present=chain_present,
        event_labels=labels,
    )


def collect_edges(experiment_dir: Path) -> list[RunEdges]:
    """Every run's edges in one experiment directory, in run-directory order.

    Runs that predate edges still appear here, with `recorded=False` — the
    caller asking "which runs have edges" needs to see them as unknown
    rather than have the row silently missing from the answer.
    """
    experiment_dir = Path(experiment_dir)
    if not experiment_dir.is_dir():
        raise EdgeReportError(f"{experiment_dir} is not a directory")

    run_dirs = sorted(p for p in experiment_dir.iterdir() if (p / "run.json").is_file())
    if not run_dirs:
        raise EdgeReportError(f"{experiment_dir} contains no runs")

    return [edges_for_run(run_dir) for run_dir in run_dirs]


def total_edges(runs: Iterable[RunEdges]) -> int | None:
    """Edges across the runs that recorded them; None if none of them did."""
    known = [run for run in runs if run.recorded]
    if not known:
        return None
    return sum(len(run.edges) for run in known)


def count_by_relationship(runs: Iterable[RunEdges]) -> dict[str, int] | None:
    """Edge count per relationship kind, over runs that recorded edges.

    Every kind in the vocabulary appears, so a kind with a real zero is
    distinguishable from a kind the tool does not know about. Returns None
    when no run recorded edges at all: the counts would be unknowns
    rendered as zeros.
    """
    known = [run for run in runs if run.recorded]
    if not known:
        return None
    counts = {str(kind): 0 for kind in RelationshipType}
    for run in known:
        for edge in run.edges:
            counts[str(edge.relationship)] += 1
    return counts


def run_edges_to_dict(run_edges: RunEdges) -> dict[str, Any]:
    """One run as JSON. `edges` is null, not [], when the run predates edges."""
    return {
        "arm": run_edges.arm,
        "edge_count": len(run_edges.edges) if run_edges.recorded else None,
        "edges": (
            [
                {
                    **edge.to_dict(),
                    "from_label": run_edges.label_for(edge.from_event_id),
                    "to_label": run_edges.label_for(edge.to_event_id),
                }
                for edge in run_edges.edges
            ]
            if run_edges.recorded
            else None
        ),
        "edges_recorded": run_edges.recorded,
        "run_id": run_edges.run_id,
        "task_id": run_edges.task_id,
    }
