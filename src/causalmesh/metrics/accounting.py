"""Coordination-cost accounting across a collection (spec §44, §45).

This module aggregates. It does not measure: every number it reports was
recorded by the channel at injection time (`InjectionAccounting`) and
persisted in the run artifact. Recomputing a cost here from event payloads
would produce a second, subtly different figure for the same quantity, and
the two would diverge the first time the channel's accounting changed.

The separation §44 asks for — task cost versus coordination cost — is
therefore read out rather than inferred: coordination bytes are what the
channel charged for peer information, and nothing else is counted as
coordination.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class MetricsError(ValueError):
    """A collection could not be read, or is internally inconsistent."""


@dataclass(frozen=True)
class RunMetrics:
    """One run's costs and outcome, as recorded.

    `succeeded` is `None` rather than False when the artifact carries no
    outcome. A run that did not report an outcome is not a failed run, and
    counting it as one would inflate every failure rate by the number of
    runs that crashed before evaluating — the confident-zero failure this
    project has already been bitten by (docs/backlog.md).
    """

    run_id: str
    arm: str
    task_id: str
    coordination_bytes: int
    coordination_tokens: int
    events: int
    denials: int
    turns: int
    succeeded: bool | None
    received_no_coordination: bool

    @property
    def outcome_known(self) -> bool:
        return self.succeeded is not None


@dataclass
class ArmMetrics:
    """Everything one arm did, across every run of it."""

    arm: str
    runs: list[RunMetrics] = field(default_factory=list)

    @property
    def run_count(self) -> int:
        return len(self.runs)

    @property
    def known_outcomes(self) -> list[RunMetrics]:
        return [run for run in self.runs if run.outcome_known]

    @property
    def unknown_outcomes(self) -> int:
        return self.run_count - len(self.known_outcomes)

    @property
    def successes(self) -> int:
        return sum(1 for run in self.known_outcomes if run.succeeded)

    @property
    def denials(self) -> int:
        return sum(run.denials for run in self.runs)

    @property
    def success_rate(self) -> float | None:
        """Successes over runs whose outcome is known.

        None for an empty denominator: a rate over zero runs is not zero,
        and returning 0.0 would put a fabricated number into a results
        table.
        """
        known = self.known_outcomes
        if not known:
            return None
        return self.successes / len(known)

    @property
    def mean_coordination_bytes(self) -> float | None:
        if not self.runs:
            return None
        return statistics.fmean(run.coordination_bytes for run in self.runs)

    @property
    def mean_coordination_tokens(self) -> float | None:
        if not self.runs:
            return None
        return statistics.fmean(run.coordination_tokens for run in self.runs)

    @property
    def bytes_per_turn(self) -> float | None:
        """Cost per agent-turn rather than per run.

        §44 cares about how cost scales with interaction, and a run with
        more turns naturally spends more. Dividing by turns makes C1 and C2
        comparable even when their runs differ in length.
        """
        turns = sum(run.turns for run in self.runs)
        if not turns:
            return None
        return sum(run.coordination_bytes for run in self.runs) / turns

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "bytes_per_turn": self.bytes_per_turn,
            "denials": self.denials,
            "mean_coordination_bytes": self.mean_coordination_bytes,
            "mean_coordination_tokens": self.mean_coordination_tokens,
            "runs": self.run_count,
            "success_rate": self.success_rate,
            "successes": self.successes,
            "unknown_outcomes": self.unknown_outcomes,
        }


@dataclass
class CollectionMetrics:
    """One experiment's costs, by arm and by task."""

    experiment_id: str
    arms: dict[str, ArmMetrics] = field(default_factory=dict)

    @property
    def run_count(self) -> int:
        return sum(arm.run_count for arm in self.arms.values())

    @property
    def task_ids(self) -> list[str]:
        return sorted({run.task_id for arm in self.arms.values() for run in arm.runs})

    def by_task(self, task_id: str) -> dict[str, ArmMetrics]:
        """The same aggregation, restricted to one task.

        A per-arm mean across tasks hides the thing this experiment exists
        to find: on `schema_handler_widen` enforcement costs nothing, and on
        `concurrent_edit_collision` it costs every success. Pooling those
        reports a middle number that describes neither.
        """
        subset: dict[str, ArmMetrics] = {}
        for arm_id, arm in self.arms.items():
            runs = [run for run in arm.runs if run.task_id == task_id]
            if runs:
                subset[arm_id] = ArmMetrics(arm=arm_id, runs=runs)
        return subset

    def is_balanced(self) -> bool:
        """Whether every arm ran the same number of times.

        An unbalanced collection is not invalid, but a contrast drawn across
        one is weaker than it looks, so the caller is told.
        """
        counts = {arm.run_count for arm in self.arms.values()}
        return len(counts) <= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "arms": {arm_id: arm.to_dict() for arm_id, arm in sorted(self.arms.items())},
            "balanced": self.is_balanced(),
            "experiment_id": self.experiment_id,
            "runs": self.run_count,
            "tasks": self.task_ids,
        }


def _read_run(path: Path) -> RunMetrics:
    """Read one run artifact into its recorded costs.

    Field names here are load-bearing and have been wrong before: the actor
    is at `event.identity.agent_id`, and success is at
    `result.outcome.succeeded` — not `result.success`, which does not exist
    and read as a confident zero for every arm.
    """
    try:
        artifact = json.loads((path / "run.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MetricsError(f"{path}: could not read run.json: {exc}") from exc

    result = artifact.get("result") or {}
    outcome = result.get("outcome")
    succeeded = outcome.get("succeeded") if isinstance(outcome, dict) else None

    summaries = (result.get("agent_summaries") or {}).values()
    coordination = [summary.get("coordination") or {} for summary in summaries]

    return RunMetrics(
        arm=artifact.get("arm") or result.get("arm") or "?",
        coordination_bytes=int(result.get("coordination_bytes") or 0),
        coordination_tokens=sum(int(c.get("coordination_tokens") or 0) for c in coordination),
        denials=len(result.get("denials") or ()),
        events=int(result.get("events") or 0),
        received_no_coordination=all(bool(c.get("received_no_coordination")) for c in coordination)
        if coordination
        else False,
        run_id=result.get("run_id") or path.name,
        succeeded=succeeded,
        task_id=result.get("task_id") or "?",
        turns=sum(int(c.get("turns") or 0) for c in coordination),
    )


def collect(experiment_dir: Path) -> CollectionMetrics:
    """Aggregate every run in one experiment directory."""
    experiment_dir = Path(experiment_dir)
    if not experiment_dir.is_dir():
        raise MetricsError(f"{experiment_dir} is not a directory")

    run_dirs = sorted(p for p in experiment_dir.iterdir() if (p / "run.json").is_file())
    if not run_dirs:
        raise MetricsError(f"{experiment_dir} contains no runs")

    metrics = CollectionMetrics(experiment_id=experiment_dir.name)
    for run_dir in run_dirs:
        run = _read_run(run_dir)
        metrics.arms.setdefault(run.arm, ArmMetrics(arm=run.arm)).runs.append(run)
    return metrics
