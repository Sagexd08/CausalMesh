"""The analysis stack: statistics computed over what a collection already recorded.

Nothing here re-derives a run outcome. §38's `TaskOutcome` (`tasks/outcome.py`)
is the sole, automatic, judgement-free primary outcome this slice measures —
this package computes *about* recorded data, never *into* that outcome.

`agreement` is the first module: inter-rater agreement (Cohen's and Fleiss'
kappa) over human coding of secondary, qualitative failure-mode data
(`docs/backlog.md`, "Multi-rater kappa coding (§53)"). It is infrastructure
for judgements an operator supplies — this package ships no rater and no
judgement of its own.
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

__all__ = [
    "AgreementError",
    "FailureModeCategory",
    "KappaResult",
    "RaterJudgement",
    "cohens_kappa",
    "fleiss_kappa",
]
