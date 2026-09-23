"""Deciding whether a run succeeded (spec §38).

§38 is uncompromising: success is

    integration tests pass  AND  induced divergence absent

and it must be determined automatically. There is no subjective field
anywhere in this module, because the primary outcome of the whole
experiment is this boolean, and a human judgement in the middle of it would
make the result unreproducible.

Both conditions are required. A run whose tests pass while the divergence
marker remains has not resolved the coordination problem — it has failed to
notice it, which is precisely the failure mode C0 is expected to exhibit
and the one an "either" rule would hide.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..isolation import Workspace, WorkspaceError
from .definition import SuccessCriteria

__all__ = [
    "AcceptanceDecision",
    "AcceptanceVerdict",
    "TaskOutcome",
    "decide_acceptance",
    "diverged_files",
    "evaluate_outcome",
    "workspace_digest",
]


@dataclass(frozen=True)
class TaskOutcome:
    """Whether a run succeeded, and the evidence for that verdict.

    Every field here is checkable after the fact. §52 requires a failure
    classification to be traceable to evidence, so the exit code, the test
    output digest and the divergence finding are all retained rather than
    reduced to the boolean.
    """

    succeeded: bool
    tests_passed: bool
    divergence_absent: bool
    exit_code: int | None = None
    divergence_found_in: str | None = None
    detail: str = ""
    evidence: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "divergence_absent": self.divergence_absent,
            "divergence_found_in": self.divergence_found_in,
            "evidence": list(self.evidence),
            "exit_code": self.exit_code,
            "succeeded": self.succeeded,
            "tests_passed": self.tests_passed,
        }


def evaluate_outcome(
    criteria: SuccessCriteria,
    *,
    workspace: Workspace,
    test_exit_code: int | None,
) -> TaskOutcome:
    """Decide a run's outcome from its workspace and its test exit code.

    The exit code is supplied rather than obtained here: running the tests
    is a tool call that must pass through the lifecycle boundary and be
    recorded (§13). Re-running them inside the evaluator would produce an
    unrecorded execution and a second, possibly different, result.
    """
    evidence: list[str] = []

    tests_passed = test_exit_code == 0
    evidence.append(f"integration_test_exit_code={test_exit_code}")
    if test_exit_code is None:
        evidence.append("integration_test_never_ran")

    divergence_absent = True
    found_in: str | None = None

    if criteria.divergence_file and criteria.divergence_marker:
        try:
            resolved = workspace.resolve(criteria.divergence_file)
        except WorkspaceError as exc:
            divergence_absent = False
            evidence.append(f"divergence_file_unresolvable={exc}")
        else:
            if not resolved.is_file():
                divergence_absent = False
                evidence.append(f"divergence_file_missing={criteria.divergence_file}")
            else:
                content = resolved.read_text(encoding="utf-8", errors="replace")
                if criteria.divergence_marker in content:
                    divergence_absent = False
                    found_in = criteria.divergence_file
                    evidence.append(f"divergence_marker_present_in={criteria.divergence_file}")
                else:
                    evidence.append(f"divergence_marker_absent={criteria.divergence_file}")
    else:
        evidence.append("no_divergence_check_configured")

    succeeded = tests_passed and divergence_absent

    if succeeded:
        detail = "integration tests passed and no induced divergence remains"
    elif not tests_passed and not divergence_absent:
        detail = "integration tests failed and induced divergence remains"
    elif not tests_passed:
        detail = f"integration tests failed (exit code {test_exit_code})"
    else:
        detail = f"induced divergence remains in {found_in}"

    return TaskOutcome(
        succeeded=succeeded,
        tests_passed=tests_passed,
        divergence_absent=divergence_absent,
        exit_code=test_exit_code,
        divergence_found_in=found_in,
        detail=detail,
        evidence=tuple(evidence),
    )


class AcceptanceVerdict(StrEnum):
    """The decided fate of a run, distinct from the outcome it was read from.

    `HUMAN_REVIEW` is part of the vocabulary but not yet reachable: the rule
    below is a total function of `TaskOutcome.succeeded`, so every run lands
    on `ACCEPT` or `REJECT`. It is declared now, the same way
    `RunState.TIMED_OUT` is declared before anything assigns it, so that a
    future rule with a genuine third case is a change to `decide_acceptance`
    rather than a schema version bump.
    """

    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    HUMAN_REVIEW = "HUMAN_REVIEW"


@dataclass(frozen=True)
class AcceptanceDecision:
    """A run's acceptance, recorded as a decision rather than reconstructed.

    `evidence` is the outcome's own evidence tuple, not a copy or a summary
    of it — the decision points at what it was based on instead of
    restating it, so the two can never drift apart.
    """

    verdict: AcceptanceVerdict
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": list(self.evidence),
            "verdict": str(self.verdict),
        }


def decide_acceptance(outcome: TaskOutcome) -> AcceptanceDecision:
    """Decide a run's acceptance from its outcome.

    §38 already made this a total, automatic function of `succeeded` — this
    only gives that function's result a name and a place to be signed and
    recorded. No probabilistic call belongs here: given the current state
    there is exactly one correct verdict, which is precisely the condition
    the Jev backlog entry names as disqualifying a decision point from
    trading a deterministic answer for a calibrated one.
    """
    verdict = AcceptanceVerdict.ACCEPT if outcome.succeeded else AcceptanceVerdict.REJECT
    return AcceptanceDecision(verdict=verdict, evidence=outcome.evidence)


def workspace_digest(workspace: Workspace) -> dict[str, str]:
    """SHA-256 of every file in a workspace, for divergence analysis.

    Comparing two agents' workspaces after a run shows exactly which files
    diverged — the raw material for the conflicting-edit and redundant-work
    metrics (§44), computed from artifacts rather than inferred from the
    event log alone.
    """
    digests = {}
    for relative in workspace.list_files():
        path = workspace.resolve(relative)
        digests[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def diverged_files(left: dict[str, str], right: dict[str, str]) -> tuple[str, ...]:
    """Files whose contents differ between two workspaces."""
    return tuple(
        sorted(path for path in set(left) | set(right) if left.get(path) != right.get(path))
    )
