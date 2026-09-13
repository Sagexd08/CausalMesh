"""The experimental design: arms, profiles and reproducible randomization.

Spec §2, §39 to §41. This package describes the experiment; it does not
execute it. The separation is load-bearing for §5: the analysis layer must
be able to read the design — which arms exist, what each contrast isolates
— without importing the runtime that produced the data.
"""

from __future__ import annotations

from .arms import (
    ARM_IDS,
    ARMS,
    PRIMARY_CONTRASTS,
    Arm,
    Contrast,
    Enforcement,
    Information,
    arm,
    contrast,
)
from .profiles import PROFILE_NAMES, PROFILES, Profile, ProfileError, profile
from .randomization import (
    PlannedRun,
    RunPlan,
    derive_run_seed,
    plan_experiment,
    shuffled,
)

__all__ = [
    "ARMS",
    "ARM_IDS",
    "PRIMARY_CONTRASTS",
    "PROFILES",
    "PROFILE_NAMES",
    "Arm",
    "Contrast",
    "Enforcement",
    "Information",
    "PlannedRun",
    "Profile",
    "ProfileError",
    "RunPlan",
    "arm",
    "contrast",
    "derive_run_seed",
    "plan_experiment",
    "profile",
    "shuffled",
]
