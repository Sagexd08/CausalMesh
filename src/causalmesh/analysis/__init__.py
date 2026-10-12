"""The analysis stack: statistics computed over what a collection already recorded.

Nothing here re-derives a run outcome. §38's `TaskOutcome` (`tasks/outcome.py`)
is the sole, automatic, judgement-free primary outcome this slice measures —
this package computes *about* recorded data, never *into* that outcome.

`agreement` is the first module: inter-rater agreement (Cohen's and Fleiss'
kappa) over human coding of secondary, qualitative failure-mode data
(`docs/backlog.md`, "Multi-rater kappa coding (§53)"). It is infrastructure
for judgements an operator supplies — this package ships no rater and no
judgement of its own.

`inference` is the second: interval, exact-test, multiplicity, equivalence and
power primitives over counts a caller supplies (`docs/PLAN.md` Step 13,
primitives only). Nothing in it is preregistered: every assumption (alpha,
confidence, margin) is a required argument, and the mixed-effects model is not
built (`docs/backlog.md`).
"""

from __future__ import annotations

from .agreement import (
    AgreementError,
    FailureModeCategory,
    KappaResult,
    RaterJudgement,
    cohens_kappa,
    fleiss_kappa,
)
from .inference import (
    DifferenceInterval,
    EquivalenceResult,
    FisherResult,
    HolmResult,
    InferenceError,
    OutcomeTally,
    PowerResult,
    ProportionInterval,
    SampleSizeResult,
    equivalence_by_interval,
    fisher_exact,
    holm_bonferroni,
    n_per_arm_for_power,
    newcombe_difference,
    power_two_proportions,
    tally_outcomes,
    wilson_interval,
)

__all__ = [
    "AgreementError",
    "DifferenceInterval",
    "EquivalenceResult",
    "FailureModeCategory",
    "FisherResult",
    "HolmResult",
    "InferenceError",
    "KappaResult",
    "OutcomeTally",
    "PowerResult",
    "ProportionInterval",
    "RaterJudgement",
    "SampleSizeResult",
    "cohens_kappa",
    "equivalence_by_interval",
    "fisher_exact",
    "fleiss_kappa",
    "holm_bonferroni",
    "n_per_arm_for_power",
    "newcombe_difference",
    "power_two_proportions",
    "tally_outcomes",
    "wilson_interval",
]
