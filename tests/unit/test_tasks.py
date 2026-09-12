"""Task definition, validation and outcome (spec §35 to §38).

The validator's job is to keep unusable tasks out of the experiment before
they waste a collection. Two of its rules were corrected by running real
tasks against them, and both corrections are pinned here:

- a task is coordination-sensitive through **contention or dependency**,
  not contention alone;
- a divergence file must be **written by someone**, but need not be
  contested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.isolation import Workspace
from causalmesh.tasks import (
    SuccessCriteria,
    TaskDefinition,
    TaskError,
    TaskFamily,
    diverged_files,
    evaluate_outcome,
    validate_structure,
    workspace_digest,
)

pytestmark = pytest.mark.unit


def minimal_task(**overrides) -> dict:
    data = {
        "task_id": "t1",
        "version": "1.0.0",
        "family": TaskFamily.SCHEMA_HANDLER,
        "fixture": "schema_handler",
        "roles": [
            {"agent_id": "agent_a", "owns": ["src/schema.py"]},
            {"agent_id": "agent_b", "owns": ["src/handler.py"], "depends_on": ["src/schema.py"]},
        ],
        "scenario": {
            "agent_a": {"actions": [{"write": "src/schema.py"}]},
            "agent_b": {"actions": [{"read": "src/schema.py"}, {"write": "src/handler.py"}]},
        },
        "success": {
            "divergence_file": "src/handler.py",
            "divergence_marker": "STALE",
        },
    }
    data.update(overrides)
    return data


class TestDefinition:
    def test_a_well_formed_task_loads(self) -> None:
        task = TaskDefinition.from_dict(minimal_task())
        assert task.task_id == "t1"
        assert task.agent_ids == ("agent_a", "agent_b")

    def test_a_missing_field_is_refused(self) -> None:
        data = minimal_task()
        del data["fixture"]
        with pytest.raises(TaskError, match="missing required field"):
            TaskDefinition.from_dict(data)

    def test_an_unknown_family_is_refused(self) -> None:
        with pytest.raises(TaskError, match="unknown family"):
            TaskDefinition.from_dict(minimal_task(family="not_a_family"))

    def test_a_single_agent_task_is_refused(self) -> None:
        # Coordination needs at least two parties.
        with pytest.raises(TaskError, match="at least two agents"):
            TaskDefinition.from_dict(
                minimal_task(
                    roles=[{"agent_id": "solo"}],
                    scenario={"solo": {"actions": [{"write": "a.py"}]}},
                )
            )

    def test_roles_and_scenario_must_agree(self) -> None:
        # A mismatch means an agent runs without a declared role, or a
        # declared role never acts.
        with pytest.raises(TaskError, match="disagree about the agents"):
            TaskDefinition.from_dict(
                minimal_task(scenario={"agent_a": {"actions": [{"write": "x.py"}]}})
            )

    def test_a_missing_version_is_refused(self) -> None:
        with pytest.raises(TaskError, match="version is required"):
            TaskDefinition.from_dict(minimal_task(version=""))

    def test_duplicate_agent_ids_are_refused(self) -> None:
        with pytest.raises(TaskError, match="duplicate agent ids"):
            TaskDefinition.from_dict(
                minimal_task(
                    roles=[{"agent_id": "agent_a"}, {"agent_id": "agent_a"}],
                    scenario={"agent_a": {"actions": [{"write": "x.py"}]}},
                )
            )


class TestContentHash:
    def test_the_hash_is_stable(self) -> None:
        task = TaskDefinition.from_dict(minimal_task())
        assert len({task.content_hash() for _ in range(10)}) == 1

    def test_the_hash_changes_with_the_scenario(self) -> None:
        # §33: a silently edited task must be detectable rather than
        # producing results pooled with incompatible ones.
        original = TaskDefinition.from_dict(minimal_task())
        edited = TaskDefinition.from_dict(
            minimal_task(
                scenario={
                    "agent_a": {"actions": [{"write": "src/schema.py"}]},
                    "agent_b": {"actions": [{"write": "src/handler.py"}]},
                }
            )
        )
        assert original.content_hash() != edited.content_hash()

    def test_the_hash_changes_with_the_version(self) -> None:
        a = TaskDefinition.from_dict(minimal_task(version="1.0.0"))
        b = TaskDefinition.from_dict(minimal_task(version="1.0.1"))
        assert a.content_hash() != b.content_hash()


class TestCoordinationSensitivityRule:
    """The rule that was corrected by running a real task against it."""

    def test_a_dependency_alone_is_sufficient(self) -> None:
        """agent_b depends on a file agent_a writes; nobody contests anything.

        This shape was verified empirically to separate the arms — C0 fails,
        C1/C2/C3 succeed — so a validator demanding contention would reject
        a task that demonstrably works.
        """
        task = TaskDefinition.from_dict(minimal_task())
        report = validate_structure(task)
        assert report.valid, [i.detail for i in report.errors]

    def test_contention_alone_is_sufficient(self) -> None:
        task = TaskDefinition.from_dict(
            minimal_task(
                roles=[
                    {"agent_id": "agent_a", "owns": ["src/shared.py"]},
                    {"agent_id": "agent_b"},
                ],
                scenario={
                    "agent_a": {"actions": [{"write": "src/shared.py"}]},
                    "agent_b": {"actions": [{"write": "src/shared.py"}]},
                },
                success={"divergence_file": "src/shared.py", "divergence_marker": "X"},
            )
        )
        assert validate_structure(task).valid

    def test_neither_is_refused(self) -> None:
        # Nothing one agent does can invalidate the other's work.
        task = TaskDefinition.from_dict(
            minimal_task(
                roles=[{"agent_id": "agent_a"}, {"agent_id": "agent_b"}],
                scenario={
                    "agent_a": {"actions": [{"write": "a.py"}]},
                    "agent_b": {"actions": [{"write": "b.py"}]},
                },
                success={"divergence_file": "a.py", "divergence_marker": "X"},
            )
        )
        report = validate_structure(task)
        assert not report.valid
        assert any(i.code == "no_coordination_dependency" for i in report.errors)


class TestValidationRules:
    def test_a_missing_fixture_is_an_error(self, tmp_path: Path) -> None:
        task = TaskDefinition.from_dict(minimal_task(fixture="does_not_exist"))
        report = validate_structure(task, fixtures_root=tmp_path)
        assert any(i.code == "fixture_missing" for i in report.errors)

    def test_an_unwritten_divergence_file_is_an_error(self) -> None:
        # The marker could never change, so the check would be vacuous.
        task = TaskDefinition.from_dict(
            minimal_task(
                success={"divergence_file": "never/written.py", "divergence_marker": "X"}
            )
        )
        report = validate_structure(task)
        assert any(i.code == "divergence_unreachable" for i in report.errors)

    def test_a_written_but_uncontested_divergence_file_is_accepted(self) -> None:
        """The second corrected rule.

        Stale-dependency defects show up in a file only one agent writes,
        invalidated by a peer's write elsewhere. Requiring contention here
        would reject the entire schema/handler family.
        """
        task = TaskDefinition.from_dict(minimal_task())
        report = validate_structure(task)
        assert not any(i.code == "divergence_unreachable" for i in report.issues)
        assert report.valid

    def test_a_half_specified_divergence_check_is_an_error(self) -> None:
        task = TaskDefinition.from_dict(
            minimal_task(success={"divergence_marker": "X"})
        )
        report = validate_structure(task)
        assert any(i.code == "incomplete_divergence_check" for i in report.errors)

    def test_an_empty_action_list_is_an_error(self) -> None:
        task = TaskDefinition.from_dict(
            minimal_task(
                scenario={
                    "agent_a": {"actions": [{"write": "src/schema.py"}]},
                    "agent_b": {"actions": []},
                }
            )
        )
        report = validate_structure(task)
        assert any(i.code == "role_inactive" for i in report.errors)

    def test_an_untouched_dependency_is_a_warning_not_an_error(self) -> None:
        # Misleading, but not fatal: it would skew relevance scoring.
        task = TaskDefinition.from_dict(
            minimal_task(
                roles=[
                    {"agent_id": "agent_a", "owns": ["src/schema.py"]},
                    {
                        "agent_id": "agent_b",
                        "owns": ["src/handler.py"],
                        "depends_on": ["src/schema.py", "src/never_read.py"],
                    },
                ]
            )
        )
        report = validate_structure(task)
        assert report.valid
        assert any(i.code == "dependency_untouched" for i in report.warnings)

    def test_a_declared_contention_that_does_not_happen_is_an_error(self) -> None:
        task = TaskDefinition.from_dict(
            minimal_task(contested_paths=["src/schema.py"])
        )
        report = validate_structure(task)
        assert any(i.code == "contention_mismatch" for i in report.errors)


class TestOutcome:
    """§38: success is tests passing AND divergence absent. Both."""

    @pytest.fixture
    def workspace(self, tmp_path: Path) -> Workspace:
        workspace = Workspace.create(base=tmp_path, run_id="r", agent_id="a")
        (workspace.root / "src").mkdir()
        (workspace.root / "src" / "handler.py").write_text("clean\n", encoding="utf-8")
        return workspace

    def test_passing_tests_and_no_divergence_succeeds(self, workspace: Workspace) -> None:
        outcome = evaluate_outcome(
            SuccessCriteria(divergence_file="src/handler.py", divergence_marker="STALE"),
            workspace=workspace,
            test_exit_code=0,
        )
        assert outcome.succeeded

    def test_failing_tests_alone_is_enough_to_fail(self, workspace: Workspace) -> None:
        outcome = evaluate_outcome(
            SuccessCriteria(divergence_file="src/handler.py", divergence_marker="STALE"),
            workspace=workspace,
            test_exit_code=1,
        )
        assert not outcome.succeeded
        assert outcome.divergence_absent

    def test_divergence_alone_is_enough_to_fail(self, workspace: Workspace) -> None:
        """The case an "either" rule would hide.

        Tests pass but the marker remains: the agents did not resolve the
        coordination problem, they failed to notice it. That is exactly the
        C0 failure mode.
        """
        (workspace.root / "src" / "handler.py").write_text("STALE\n", encoding="utf-8")
        outcome = evaluate_outcome(
            SuccessCriteria(divergence_file="src/handler.py", divergence_marker="STALE"),
            workspace=workspace,
            test_exit_code=0,
        )
        assert not outcome.succeeded
        assert outcome.tests_passed
        assert outcome.divergence_found_in == "src/handler.py"

    def test_a_missing_divergence_file_is_not_treated_as_clean(
        self, workspace: Workspace
    ) -> None:
        # The check could not be performed; reporting success on that basis
        # would be a false negative in the primary outcome.
        outcome = evaluate_outcome(
            SuccessCriteria(divergence_file="src/absent.py", divergence_marker="X"),
            workspace=workspace,
            test_exit_code=0,
        )
        assert not outcome.succeeded
        assert "divergence_file_missing=src/absent.py" in outcome.evidence

    def test_tests_that_never_ran_are_distinguishable_from_failure(
        self, workspace: Workspace
    ) -> None:
        outcome = evaluate_outcome(
            SuccessCriteria(), workspace=workspace, test_exit_code=None
        )
        assert not outcome.succeeded
        assert "integration_test_never_ran" in outcome.evidence

    def test_every_verdict_carries_evidence(self, workspace: Workspace) -> None:
        # §52: a classification must be traceable, never intuited.
        outcome = evaluate_outcome(
            SuccessCriteria(divergence_file="src/handler.py", divergence_marker="STALE"),
            workspace=workspace,
            test_exit_code=0,
        )
        assert outcome.evidence
        assert any("exit_code" in item for item in outcome.evidence)


class TestWorkspaceDivergence:
    def test_identical_workspaces_diverge_nowhere(self, tmp_path: Path) -> None:
        digests = {}
        for agent in ("a", "b"):
            workspace = Workspace.create(base=tmp_path, run_id="r", agent_id=agent)
            (workspace.root / "x.py").write_text("same\n", encoding="utf-8")
            digests[agent] = workspace_digest(workspace)
        assert diverged_files(digests["a"], digests["b"]) == ()

    def test_a_differing_file_is_reported(self, tmp_path: Path) -> None:
        digests = {}
        for agent, content in (("a", "one\n"), ("b", "two\n")):
            workspace = Workspace.create(base=tmp_path, run_id="r", agent_id=agent)
            (workspace.root / "x.py").write_text(content, encoding="utf-8")
            digests[agent] = workspace_digest(workspace)
        assert diverged_files(digests["a"], digests["b"]) == ("x.py",)

    def test_a_file_present_in_only_one_workspace_diverges(self, tmp_path: Path) -> None:
        a = Workspace.create(base=tmp_path, run_id="r", agent_id="a")
        (a.root / "only_a.py").write_text("x\n", encoding="utf-8")
        b = Workspace.create(base=tmp_path, run_id="r", agent_id="b")
        assert diverged_files(workspace_digest(a), workspace_digest(b)) == ("only_a.py",)
