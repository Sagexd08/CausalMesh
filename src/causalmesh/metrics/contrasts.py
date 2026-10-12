"""Measured differences across the four planned contrasts (spec §46).

The contrasts themselves live in `experiments/arms.py`, because which
comparisons the design makes is a property of the design and not of any
particular collection. This module only applies them to data.

**These are descriptive differences, not inferential results.** No interval,
no p-value, no claim that a difference is distinguishable from noise — that
is `causalmesh report`'s (Step 13 primitives), under assumptions the caller
states, and the mixed-effects model is not built. A difference reported
here says what the runs did, not what the population does. §50 requires a
non-significant difference to be stated as such rather than as equivalence;
the honest position before the statistics exist is to make no significance
claim at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from causalmesh.experiments.arms import PRIMARY_CONTRASTS, Contrast
from causalmesh.metrics.accounting import ArmMetrics, CollectionMetrics


@dataclass(frozen=True)
class ContrastResult:
    """One contrast, measured on one collection.

    Every difference is `treatment - baseline`, so a positive success delta
    means the treatment arm did better and a positive cost delta means it
    spent more. Fixing that direction once here stops each reader from
    having to work out the sign.
    """

    name: str
    baseline: str
    treatment: str
    isolates: str
    baseline_runs: int
    treatment_runs: int
    baseline_success_rate: float | None
    treatment_success_rate: float | None
    baseline_bytes: float | None
    treatment_bytes: float | None

    @property
    def success_delta(self) -> float | None:
        if self.baseline_success_rate is None or self.treatment_success_rate is None:
            return None
        return self.treatment_success_rate - self.baseline_success_rate

    @property
    def bytes_delta(self) -> float | None:
        if self.baseline_bytes is None or self.treatment_bytes is None:
            return None
        return self.treatment_bytes - self.baseline_bytes

    @property
    def bytes_ratio(self) -> float | None:
        """Treatment cost as a fraction of baseline cost.

        Reported as a fraction rather than a percentage saving because the
        two are easy to confuse: 196/361 is 0.54, which is a 46% saving, and
        writing "46%" next to a ratio invites the wrong one being quoted.
        """
        if not self.baseline_bytes or self.treatment_bytes is None:
            return None
        return self.treatment_bytes / self.baseline_bytes

    @property
    def measurable(self) -> bool:
        """Whether both arms produced enough data to compare at all."""
        return self.baseline_runs > 0 and self.treatment_runs > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "baseline_bytes": self.baseline_bytes,
            "baseline_runs": self.baseline_runs,
            "baseline_success_rate": self.baseline_success_rate,
            "bytes_delta": self.bytes_delta,
            "bytes_ratio": self.bytes_ratio,
            "isolates": self.isolates,
            "measurable": self.measurable,
            "name": self.name,
            "success_delta": self.success_delta,
            "treatment": self.treatment,
            "treatment_bytes": self.treatment_bytes,
            "treatment_runs": self.treatment_runs,
            "treatment_success_rate": self.treatment_success_rate,
        }


def _empty(arm_id: str) -> ArmMetrics:
    return ArmMetrics(arm=arm_id)


def measure(
    metrics: CollectionMetrics,
    *,
    contrasts: tuple[Contrast, ...] = PRIMARY_CONTRASTS,
    task_id: str | None = None,
) -> list[ContrastResult]:
    """Apply the planned contrasts to a collection.

    `task_id` restricts the comparison to one task. That matters here more
    than it usually would: enforcement costs nothing on a task with disjoint
    ownership and costs every success on a contested one, so a pooled
    enforcement contrast describes neither task.
    """
    arms = metrics.by_task(task_id) if task_id is not None else metrics.arms

    results = []
    for contrast in contrasts:
        baseline = arms.get(contrast.baseline, _empty(contrast.baseline))
        treatment = arms.get(contrast.treatment, _empty(contrast.treatment))
        results.append(
            ContrastResult(
                baseline=contrast.baseline,
                baseline_bytes=baseline.mean_coordination_bytes,
                baseline_runs=baseline.run_count,
                baseline_success_rate=baseline.success_rate,
                isolates=contrast.isolates,
                name=contrast.name,
                treatment=contrast.treatment,
                treatment_bytes=treatment.mean_coordination_bytes,
                treatment_runs=treatment.run_count,
                treatment_success_rate=treatment.success_rate,
            )
        )
    return results
