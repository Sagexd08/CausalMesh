"""The scalability profile: coordination cost beyond four agents (spec §86).

The other profiles fix *how many* runs of the same two-agent tasks to make.
This one varies a different axis, the number of agents, and asks one
question of it: how does the cost of delivering coordination information
grow with N, under broadcast delivery and under path-scoped delivery?

It is a profile in the same sense as the others (a named, fixed scale that
says nothing about the design beyond that), but it does not fit `Profile`:
`Profile` multiplies tasks by arms by repetitions, and this one multiplies
agent counts by delivery modes by arms by topologies. Forcing it into
`PROFILES` would either change `plan_experiment`'s run counts, which the
existing profiles and the 1920-run confirmatory design rely on, or make
`Profile` mean two things. So it lives beside them, with its own registry.

**It is not gated.** The confirmatory gate exists because running that
collection commits to a preregistered analysis. This profile registers no
hypothesis and reports measured costs of scripted mock agents; nothing it
prints is evidence about how real agents behave.

This module describes the profile. It does not run it; `tasks.scalability`
does, so the analysis layer can read the design without importing the
runtime (§5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEFAULT_GROUP_SIZE",
    "DENSE",
    "LOCALIZED",
    "SCALABILITY_PROFILES",
    "SCALABILITY_PROFILE_NAMES",
    "TOPOLOGIES",
    "ScalabilityProfile",
    "scalability_profile",
]

# The delivery-mode names are spelled out here rather than imported from
# `relay.delivery`, so reading the design never loads the relay (§5). A test
# pins them equal to the relay's constants, so they cannot drift.
BROADCAST = "broadcast"
PATH_SCOPED = "path_scoped"
DELIVERY_MODES: tuple[str, ...] = (BROADCAST, PATH_SCOPED)

DEFAULT_GROUP_SIZE = 4
"""How many agents contest each shared path in the `localized` topology."""

LOCALIZED = "localized"
DENSE = "dense"
TOPOLOGIES: tuple[str, ...] = (LOCALIZED, DENSE)


@dataclass(frozen=True, slots=True)
class ScalabilityProfile:
    """One fixed scale for the scalability measurement.

    `topologies` names how contention is laid out as N grows. `localized`
    keeps each shared path contested by `group_size` agents however large N
    is; `dense` has every agent contest the same path, which is the case
    where interest-scoped delivery has nothing to remove on the shared path.
    Reporting both keeps the result from resting on the favourable topology
    alone.
    """

    name: str
    agent_counts: tuple[int, ...]
    delivery_modes: tuple[str, ...] = DELIVERY_MODES
    arms: tuple[str, ...] = ("C1", "C2")
    topologies: tuple[str, ...] = TOPOLOGIES
    group_size: int = DEFAULT_GROUP_SIZE
    own_files: int = 2
    gated: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        if len(self.agent_counts) < 2:
            raise ValueError("a scalability profile needs at least two agent counts to fit a trend")
        if BROADCAST not in self.delivery_modes:
            raise ValueError("broadcast is the baseline and must always be measured")
        for arm in self.arms:
            if arm.upper() == "C0":
                raise ValueError("C0 delivers nothing, so it has no delivery cost to scale")
        unknown = set(self.topologies) - set(TOPOLOGIES)
        if unknown:
            raise ValueError(f"unknown topologies {sorted(unknown)}; expected {list(TOPOLOGIES)}")

    def run_count(self) -> int:
        """How many runs the profile implies.

        Computed, not stored, like `Profile.run_count`: stored counts go
        stale the moment a dimension changes.
        """
        return (
            len(self.agent_counts)
            * len(self.delivery_modes)
            * len(self.arms)
            * len(self.topologies)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_counts": list(self.agent_counts),
            "arms": list(self.arms),
            "delivery_modes": list(self.delivery_modes),
            "description": self.description,
            "gated": self.gated,
            "group_size": self.group_size,
            "name": self.name,
            "own_files": self.own_files,
            "run_count": self.run_count(),
            "topologies": list(self.topologies),
        }


SCALABILITY_PROFILES: dict[str, ScalabilityProfile] = {
    "scalability": ScalabilityProfile(
        name="scalability",
        agent_counts=(4, 8, 16),
        description=(
            "N in {4, 8, 16} agents, broadcast versus path-scoped delivery, "
            "transcript (C1) and metadata (C2) channels, localized and dense "
            "contention. Scripted mock agents; reports measured delivery and "
            "coordination cost, not agent behaviour."
        ),
    ),
    "scalability_smoke": ScalabilityProfile(
        name="scalability_smoke",
        agent_counts=(4, 8),
        arms=("C2",),
        topologies=(LOCALIZED,),
        description=(
            "Two sizes, one arm, one topology. Answers only 'does the machinery run "
            "at N above 4'; two points cannot show a growth rate."
        ),
    ),
}

SCALABILITY_PROFILE_NAMES: tuple[str, ...] = tuple(SCALABILITY_PROFILES)


def scalability_profile(name: str) -> ScalabilityProfile:
    """Look up a scalability profile, refusing an unknown one."""
    try:
        return SCALABILITY_PROFILES[name]
    except KeyError:
        raise ValueError(
            f"unknown scalability profile {name!r}; defined: {sorted(SCALABILITY_PROFILES)}"
        ) from None
