"""Reproducible randomization and the experiment plan (spec §39, §40, §41).

Two things happen here, and they are separate on purpose.

**Assignment (§39).** The design is fully crossed: every task is run under
every arm, the same number of times. There is no random *allocation* to
conditions at all, because there is nothing to allocate — the same task can
be run repeatedly, so pairing each task with all four arms removes
between-condition variance entirely. Randomization exists to protect against
*order* effects, not to balance groups.

**Ordering (§41).** Execution order is randomized so that anything drifting
over the course of a collection — a warming cache, a filling disk, a machine
getting busier — cannot align with an arm. If arms ran in blocks, C0 would
occupy the cold start of every collection and its results would be
confounded with machine state.

**Every draw is derived, never sampled (§40).** The order is a deterministic
permutation of `HKDF(master_seed, "plan/" + experiment_id)`, and each run's
own seed is `HKDF(master_seed, run_id)`. No `random.random()`, no clock, no
`os.urandom`. This is stricter than it needs to be for order alone, and the
reason is §84: an experiment that cannot be re-executed from its recorded
seed cannot be independently checked, and a single unrecorded draw anywhere
in the pipeline breaks that for the whole collection.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from typing import Any

from ..events.canonical import canonicalize
from .arms import arm as lookup_arm
from .profiles import Profile

__all__ = [
    "PlannedRun",
    "RunPlan",
    "derive_run_seed",
    "plan_experiment",
    "shuffled",
]

_PLAN_INFO = b"causalmesh/plan/v1"
_RUN_SEED_INFO = b"causalmesh/run-seed/v1"


def _derive(master_seed: bytes, label: str, info: bytes) -> bytes:
    """A deterministic 32-byte draw from a seed and a label.

    HMAC-SHA256 rather than a bare hash of the concatenation: `seed || label`
    is ambiguous when either part can vary in length, so two different
    (seed, label) pairs could produce the same input bytes. HMAC's own
    padding removes the ambiguity, and it is in the standard library.
    """
    if not master_seed:
        raise ValueError("master_seed is required; an unseeded plan is not reproducible")
    return hmac.new(master_seed, info + b"\x00" + label.encode("utf-8"), hashlib.sha256).digest()


def derive_run_seed(master_seed: bytes, run_id: str) -> bytes:
    """The seed one run uses, derived from the collection's master seed.

    Per-run rather than shared, so a run can be re-executed on its own
    without replaying the whole collection, and so two runs of the same
    task under the same arm are not byte-identical by construction — which
    would hide any nondeterminism the harness had accidentally introduced.
    """
    return _derive(master_seed, run_id, _RUN_SEED_INFO)


def shuffled(items: list[Any], master_seed: bytes, label: str) -> list[Any]:
    """A deterministic permutation, from the seed alone.

    A Fisher-Yates shuffle whose index stream comes from a counter-mode
    hash of the derived key. `random.Random(seed).shuffle` would also be
    deterministic, but only for one CPython version: the Mersenne Twister
    seeding and the shuffle algorithm are implementation details with no
    cross-version guarantee, and §84 requires reproducibility across
    machines and versions, not merely across two runs on this laptop.
    """
    key = _derive(master_seed, label, _PLAN_INFO)
    result = list(items)
    counter = 0
    for i in range(len(result) - 1, 0, -1):
        bound = i + 1
        limit = (2**64 // bound) * bound
        while True:
            block = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
            counter += 1
            draw = int.from_bytes(block[:8], "big")
            if draw < limit:
                break
        j = draw % bound
        result[i], result[j] = result[j], result[i]
    return result


@dataclass(frozen=True, slots=True)
class PlannedRun:
    """One unit of work: a task under an arm, at a repetition index.

    The `run_id` is derived from the coordinates rather than generated, so
    re-planning the same experiment yields the same identifiers and a
    resumed collection can recognise what it already did (§42). A UUID
    would make every replan a different set of runs and defeat resume.
    """

    run_id: str
    experiment_id: str
    task_id: str
    arm: str
    repetition: int
    order: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "experiment_id": self.experiment_id,
            "order": self.order,
            "repetition": self.repetition,
            "run_id": self.run_id,
            "task_id": self.task_id,
        }


@dataclass(frozen=True)
class RunPlan:
    """A complete, ordered collection of runs.

    Produced before anything executes and hashed, so what was *intended*
    can be compared with what actually happened. A collection that quietly
    ran fewer runs than it planned is then visible as a gap rather than
    invisible as a smaller denominator (§81).
    """

    experiment_id: str
    profile: str
    runs: tuple[PlannedRun, ...]
    task_ids: tuple[str, ...]
    arms: tuple[str, ...]
    repetitions: int
    task_hashes: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.runs)

    def for_arm(self, arm_id: str) -> tuple[PlannedRun, ...]:
        return tuple(run for run in self.runs if run.arm == arm_id)

    def for_task(self, task_id: str) -> tuple[PlannedRun, ...]:
        return tuple(run for run in self.runs if run.task_id == task_id)

    def is_balanced(self) -> bool:
        """Whether every (task, arm) cell holds the same number of runs.

        The fully crossed design's defining property. Checked rather than
        assumed because a plan built from a filtered task list, or one
        truncated by `max_tasks`, could silently lose a cell — and an
        unbalanced design changes what the mixed-effects model in §48 is
        estimating.
        """
        counts: dict[tuple[str, str], int] = {}
        for run in self.runs:
            counts[(run.task_id, run.arm)] = counts.get((run.task_id, run.arm), 0) + 1
        expected = len(self.task_ids) * len(self.arms)
        return len(counts) == expected and len(set(counts.values())) == 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "arms": list(self.arms),
            "experiment_id": self.experiment_id,
            "profile": self.profile,
            "repetitions": self.repetitions,
            "run_count": len(self.runs),
            "runs": [run.to_dict() for run in self.runs],
            "task_hashes": dict(sorted(self.task_hashes.items())),
            "task_ids": list(self.task_ids),
        }

    def content_hash(self) -> str:
        """A digest of the plan, including the order.

        Order is part of the identity: two collections that ran the same
        runs in different orders are not the same experiment, because
        order is exactly what the randomization is protecting against.
        """
        return hashlib.sha256(canonicalize(self.to_dict())).hexdigest()


def plan_experiment(
    *,
    experiment_id: str,
    profile: Profile,
    task_ids: list[str],
    master_seed: bytes,
    task_hashes: dict[str, str] | None = None,
) -> RunPlan:
    """Build the full, ordered plan for a collection.

    Fully crossed: every task under every arm, `repetitions` times. The
    order is then randomized as one flat sequence rather than shuffled
    within blocks, so no arm can systematically occupy any part of the
    collection.
    """
    if not task_ids:
        raise ValueError("cannot plan an experiment with no tasks")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError(f"duplicate task ids in plan: {task_ids}")

    for arm_id in profile.arms:
        lookup_arm(arm_id)

    selected = sorted(task_ids)
    if profile.max_tasks is not None:
        selected = selected[: profile.max_tasks]

    unordered: list[PlannedRun] = []
    for task_id in selected:
        for arm_id in profile.arms:
            for repetition in range(profile.repetitions):
                unordered.append(
                    PlannedRun(
                        run_id=f"{experiment_id}__{task_id}__{arm_id}__r{repetition:04d}",
                        experiment_id=experiment_id,
                        task_id=task_id,
                        arm=arm_id,
                        repetition=repetition,
                        order=-1,
                    )
                )

    permuted = shuffled(unordered, master_seed, f"plan/{experiment_id}")
    runs = tuple(
        PlannedRun(
            run_id=run.run_id,
            experiment_id=run.experiment_id,
            task_id=run.task_id,
            arm=run.arm,
            repetition=run.repetition,
            order=index,
        )
        for index, run in enumerate(permuted)
    )

    return RunPlan(
        experiment_id=experiment_id,
        profile=profile.name,
        runs=runs,
        task_ids=tuple(selected),
        arms=tuple(profile.arms),
        repetitions=profile.repetitions,
        task_hashes=dict(task_hashes or {}),
    )
