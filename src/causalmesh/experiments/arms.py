"""The four experimental arms as data (spec §2, §39).

The arms are the whole experiment. Everything else in this repository
exists to hold the rest of the world constant while these four differ in
exactly two factors:

    arm   information                      enforcement
    C0    none                             none
    C1    unbounded transcript             none
    C2    bounded structured metadata      none
    C3    bounded structured metadata      write claims

Declaring them here as a frozen table, rather than as strings passed
around, gives the factor structure one definition that the scheduler, the
analysis and the report all read. The contrasts in §4 are computed from
these two boolean-ish columns; if an arm's factors were implicit in a
conditional somewhere, a fifth arm could be added that no contrast knew how
to interpret.

**This module does not construct anything.** The objects that implement an
arm — delivery policy, gate, channel — are installed by `relay.delivery`,
`hooks` and `tasks.runner` respectively. Keeping the description separate
from the construction means the description can be imported by the analysis
layer, which must never import the runtime (§5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ARMS",
    "ARM_IDS",
    "PRIMARY_CONTRASTS",
    "Arm",
    "Contrast",
    "arm",
    "contrast",
]


class Information:
    """The information factor's three levels (§2)."""

    NONE = "none"
    TRANSCRIPT = "transcript"
    METADATA = "metadata"


class Enforcement:
    """The enforcement factor's two levels (§2)."""

    NONE = "none"
    CLAIMS = "claims"


@dataclass(frozen=True, slots=True)
class Arm:
    """One experimental condition.

    `information` and `enforcement` are the manipulated factors. Everything
    else on this record is descriptive: it exists so a report can name the
    arm without hard-coding prose, not so any code can branch on it.
    """

    arm_id: str
    information: str
    enforcement: str
    label: str
    description: str

    @property
    def is_informed(self) -> bool:
        return self.information != Information.NONE

    @property
    def is_enforced(self) -> bool:
        return self.enforcement != Enforcement.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm_id": self.arm_id,
            "description": self.description,
            "enforcement": self.enforcement,
            "information": self.information,
            "label": self.label,
        }


ARMS: dict[str, Arm] = {
    "C0": Arm(
        arm_id="C0",
        information=Information.NONE,
        enforcement=Enforcement.NONE,
        label="Isolated",
        description=(
            "Agents work in complete isolation. No peer events are delivered "
            "and none can be injected: the NullChannel raises rather than "
            "silently dropping, so a coordination byte reaching a C0 agent is "
            "a crash rather than a quiet contamination."
        ),
    ),
    "C1": Arm(
        arm_id="C1",
        information=Information.TRANSCRIPT,
        enforcement=Enforcement.NONE,
        label="Transcript",
        description=(
            "Agents see an unbounded conversational transcript of every peer "
            "event. Information is complete and its cost grows quadratically "
            "with turns."
        ),
    ),
    "C2": Arm(
        arm_id="C2",
        information=Information.METADATA,
        enforcement=Enforcement.NONE,
        label="Metadata",
        description=(
            "Agents see bounded, typed metadata selected by a deterministic "
            "relevance scorer within a fixed window. Information is partial "
            "and its cost grows linearly with turns."
        ),
    ),
    "C3": Arm(
        arm_id="C3",
        information=Information.METADATA,
        enforcement=Enforcement.CLAIMS,
        label="Metadata + claims",
        description=(
            "Identical information to C2, plus enforced exclusive write "
            "claims. The information channel is deliberately the same object "
            "as C2's, so the C2 to C3 difference is enforcement alone."
        ),
    ),
}

ARM_IDS: tuple[str, ...] = ("C0", "C1", "C2", "C3")


def arm(arm_id: str) -> Arm:
    """Look up an arm, refusing an unknown one.

    Raising rather than defaulting: a typo'd arm silently mapped to C0 would
    produce runs labelled as one condition and executed as another, which is
    the single most damaging error this codebase could make.
    """
    try:
        return ARMS[arm_id]
    except KeyError:
        raise ValueError(
            f"unknown arm {arm_id!r}; the experiment defines {list(ARM_IDS)}"
        ) from None


@dataclass(frozen=True, slots=True)
class Contrast:
    """A planned comparison between two arms (§4).

    `isolates` names the factor the comparison is designed to attribute the
    difference to. It is a claim about the *design*, not about the result:
    the contrast isolates the factor only because the two arms are
    identical in every other respect, which is a property this codebase
    must maintain and the tests check.
    """

    name: str
    baseline: str
    treatment: str
    isolates: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "isolates": self.isolates,
            "name": self.name,
            "rationale": self.rationale,
            "treatment": self.treatment,
        }


PRIMARY_CONTRASTS: tuple[Contrast, ...] = (
    Contrast(
        name="information_benefit",
        baseline="C0",
        treatment="C2",
        isolates="information",
        rationale=(
            "Both arms are unenforced, so any difference is attributable to "
            "agents knowing what their peers did."
        ),
    ),
    Contrast(
        name="representation",
        baseline="C1",
        treatment="C2",
        isolates="information representation",
        rationale=(
            "Both arms are informed and unenforced. They differ in how the "
            "information is represented and therefore in what it costs."
        ),
    ),
    Contrast(
        name="enforcement_benefit",
        baseline="C2",
        treatment="C3",
        isolates="enforcement",
        rationale=(
            "Both arms receive identical information through the same channel "
            "object, so the difference is enforcement alone. This is the "
            "contrast the project exists to measure."
        ),
    ),
    Contrast(
        name="complete_system",
        baseline="C1",
        treatment="C3",
        isolates="representation and enforcement jointly",
        rationale=(
            "Deliberately confounded: two factors differ at once. Reported as "
            "the end-to-end effect of a complete coordinated system, never as "
            "evidence for either factor separately."
        ),
    ),
)


def contrast(name: str) -> Contrast:
    for item in PRIMARY_CONTRASTS:
        if item.name == name:
            return item
    raise ValueError(
        f"unknown contrast {name!r}; defined: "
        f"{[c.name for c in PRIMARY_CONTRASTS]}"
    )
