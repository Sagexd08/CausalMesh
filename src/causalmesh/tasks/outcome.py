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
from typing import Any

from ..isolation import Workspace, WorkspaceError
from .definition import SuccessCriteria

__all__ = ["TaskOutcome", "diverged_files", "evaluate_outcome", "workspace_digest"]


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
            # A divergence path that escapes the workspace is a finding, not
            # a crash: the check could not be performed, so the run cannot be
            # called successful on the strength of it.
            divergence_absent = False
            evidence.append(f"divergence_file_unresolvable={exc}")
        else:
            if not resolved.is_file():
                # A missing file is not "no divergence". It means the check
                # could not be performed, and reporting success on that
                # basis would be a false negative in the primary outcome.
                divergence_absent = False
                evidence.append(f"divergence_file_missing={criteria.divergence_file}")
            else:
                content = resolved.read_text(encoding="utf-8", errors="replace")
                if criteria.divergence_marker in content:
                    divergence_absent = False
                    found_in = criteria.divergence_file
                    evidence.append(
                        f"divergence_marker_present_in={criteria.divergence_file}"
                    )
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
        sorted(
            path
            for path in set(left) | set(right)
            if left.get(path) != right.get(path)
        )
    )
