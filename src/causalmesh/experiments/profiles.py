"""Experiment profiles: how much to run (spec §39, §77).

A profile fixes the scale of a collection — how many tasks, how many
repetitions per arm — and nothing else. The design (which arms, which
contrasts) is the same at every scale, because a smoke run that exercised a
different design would not be a rehearsal of the real thing.

    smoke         1 repetition   sanity: does the machinery run at all
    pilot         3 repetitions  parameter estimates for the power analysis
    small        10 repetitions  exploratory, enough to see a large effect
    medium       30 repetitions  a real but non-confirmatory collection
    confirmatory 120 repetitions the preregistered 1920-run design

**The confirmatory profile is gated** (§77). Building the machinery and
running it are different acts: the machinery must exist and be tested, but
executing 1920 runs commits to a preregistered analysis, and this project
has not preregistered one. `confirmatory.gated` is True and the scheduler
refuses it without an explicit unlock, so no confirmatory numbers can be
produced by accident and then quoted as if they were planned.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .arms import ARM_IDS

__all__ = [
    "PROFILES",
    "PROFILE_NAMES",
    "Profile",
    "ProfileError",
    "profile",
]


class ProfileError(ValueError):
    """Raised when a profile is unknown or may not be run."""


@dataclass(frozen=True, slots=True)
class Profile:
    """The scale of one collection."""

    name: str
    repetitions: int
    arms: tuple[str, ...] = ARM_IDS
    max_tasks: int | None = None
    gated: bool = False
    gate_reason: str = ""
    description: str = ""

    def run_count(self, task_count: int) -> int:
        """How many runs this profile implies for a given task set.

        Computed rather than stored: the number of tasks is a property of
        the repository at plan time, and a stored count would go stale the
        moment a task was added.
        """
        effective = task_count if self.max_tasks is None else min(task_count, self.max_tasks)
        return effective * len(self.arms) * self.repetitions

    def to_dict(self) -> dict[str, Any]:
        return {
            "arms": list(self.arms),
            "description": self.description,
            "gate_reason": self.gate_reason,
            "gated": self.gated,
            "max_tasks": self.max_tasks,
            "name": self.name,
            "repetitions": self.repetitions,
        }


PROFILES: dict[str, Profile] = {
    "smoke": Profile(
        name="smoke",
        repetitions=1,
        max_tasks=1,
        description=(
            "One task, one repetition per arm. Answers only 'does the "
            "machinery run end to end', and its numbers must never be "
            "reported as a result: n=1 per cell estimates nothing."
        ),
    ),
    "pilot": Profile(
        name="pilot",
        repetitions=3,
        description=(
            "Small but real. Its purpose is to estimate the parameters the "
            "power analysis needs (§76), which are stored separately from "
            "the reference assumptions so an estimate is never mistaken for "
            "an assumption."
        ),
    ),
    "small": Profile(
        name="small",
        repetitions=10,
        description=(
            "Exploratory. Large enough to see a large effect, too small to "
            "claim a small one. Anything reported from it is labelled "
            "EXPLORATORY (§67)."
        ),
    ),
    "medium": Profile(
        name="medium",
        repetitions=30,
        description=(
            "A substantial collection, still not the preregistered design. "
            "Reported as EXPLORATORY unless a preregistration says otherwise."
        ),
    ),
    "confirmatory": Profile(
        name="confirmatory",
        repetitions=120,
        gated=True,
        gate_reason=(
            "The confirmatory collection is the preregistered design (§48). "
            "Running it commits to a fixed analysis, and no preregistration "
            "exists for this build. The machinery is implemented and tested; "
            "the gate stays closed so confirmatory numbers cannot be produced "
            "by accident and later quoted as planned."
        ),
        description=(
            "The full 4 arms x 4 tasks x 120 repetitions = 1920-run design."
        ),
    ),
}

PROFILE_NAMES: tuple[str, ...] = tuple(PROFILES)


def profile(name: str, *, allow_gated: bool = False) -> Profile:
    """Look up a profile, refusing an unknown or gated one.

    `allow_gated` must be passed explicitly and is surfaced by the CLI as a
    flag the operator has to type. An environment variable or a config key
    would let the gate be opened by a file nobody read; a typed flag leaves
    the decision in the shell history.
    """
    try:
        found = PROFILES[name]
    except KeyError:
        raise ProfileError(
            f"unknown profile {name!r}; defined: {sorted(PROFILES)}"
        ) from None
    if found.gated and not allow_gated:
        raise ProfileError(f"profile {name!r} is gated. {found.gate_reason}")
    return found
