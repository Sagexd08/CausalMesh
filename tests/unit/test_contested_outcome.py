"""The outcome rule for a content-level merge.

`None` and `[]` mean different things and must not be confused: `None` is "this
task does not merge, so nothing is known about conflicts"; `[]` is "it merged
and nothing conflicted". AGENTS.md: an absent field is unknown, never zero.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.isolation import Workspace
from causalmesh.tasks.definition import SuccessCriteria
from causalmesh.tasks.outcome import evaluate_outcome

pytestmark = pytest.mark.unit


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    return Workspace(agent_id="__integrated__", root=tmp_path.resolve(), run_id="t")


def _outcome(workspace: Workspace, merge_conflicts, exit_code: int | None = 0):
    return evaluate_outcome(
        SuccessCriteria(),
        workspace=workspace,
        test_exit_code=exit_code,
        merge_conflicts=merge_conflicts,
    )


def test_a_task_that_does_not_merge_records_nothing_about_conflicts(workspace: Workspace) -> None:
    outcome = _outcome(workspace, None)
    assert outcome.succeeded
    assert not any("contested_merge" in item for item in outcome.evidence)


def test_a_clean_merge_is_recorded_as_clean_not_as_absent(workspace: Workspace) -> None:
    outcome = _outcome(workspace, [])
    assert outcome.succeeded
    assert "contested_merge_clean" in outcome.evidence


def test_a_conflict_fails_the_run_even_when_the_tests_pass(workspace: Workspace) -> None:
    outcome = _outcome(workspace, ["src/a.py", "src/b.py"], exit_code=0)
    assert outcome.tests_passed is True
    assert outcome.succeeded is False
    assert "contested_merge_conflict=src/a.py" in outcome.evidence
    assert "contested_merge_conflict=src/b.py" in outcome.evidence
    assert "src/a.py, src/b.py" in outcome.detail


def test_a_conflict_does_not_hide_a_test_that_never_ran(workspace: Workspace) -> None:
    outcome = _outcome(workspace, ["src/a.py"], exit_code=None)
    assert "integration_test_never_ran" in outcome.evidence
    assert outcome.succeeded is False
