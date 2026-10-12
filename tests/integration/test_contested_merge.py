"""A contested path, resolved by merging instead of by picking a winner.

Two agents edit one file. Under `last_writer` (the default) the integrated
workspace takes one agent's whole file, so one edit is always lost. Under
`three_way` the edits are merged against the fixture; edits to different parts
of the file survive together, and edits to the same lines are reported as a
conflict that fails the run whatever the tests say.

Real agents, real workspaces and a real pytest subprocess; nothing here is
mocked except that the agents are the scripted mock agents every run uses.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from causalmesh.tasks import RunConfig, TaskDefinition, execute_task
from causalmesh.tasks.definition import ContestedMerge

pytestmark = [pytest.mark.integration, pytest.mark.slow]

SEED = b"causalmesh-contested-merge-seed1"

BASE = """def alpha():
    return "a0"


def beta():
    return "b0"


def gamma():
    return "c0"
"""

TESTS = """from src.shared import alpha, gamma


def test_both_features_are_present():
    assert alpha() == "a1"
    assert gamma() == "c1"
"""


def _write(path: str, content: str) -> dict:
    return {"write": {"path": path, "content": content}}


def _edit(old: str, new: str) -> str:
    assert old in BASE
    return BASE.replace(old, new)


def _task(*, b_edit: str, merge: str) -> TaskDefinition:
    return TaskDefinition.from_dict(
        {
            "task_id": "contested_merge_probe",
            "version": "1.0.0",
            "family": "cooperbench_import",
            "fixture": "contested_merge_probe",
            "contested_paths": ["src/shared.py"],
            "contested_merge": merge,
            "roles": [
                {"agent_id": "agent_a", "owns": [], "depends_on": ["src/shared.py"]},
                {"agent_id": "agent_b", "owns": [], "depends_on": ["src/shared.py"]},
            ],
            "scenario": {
                "agent_a": {
                    "owns": [],
                    "actions": [
                        {"read": "src/shared.py"},
                        _write("src/shared.py", _edit('"a0"', '"a1"')),
                    ],
                },
                "agent_b": {
                    "owns": [],
                    "actions": [
                        {"read": "src/shared.py"},
                        {"wait": "1s"},
                        _write("src/shared.py", b_edit),
                    ],
                },
            },
            "success": {"integration_test": ["python", "-m", "pytest", "-q", "tests/"]},
        }
    )


@pytest.fixture
def fixtures(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures" / "contested_merge_probe"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    # newline="\n": on Windows `write_text` would write CRLF while the scripted agents
    # write LF, so the fixture would differ from both sides on every line.
    (root / "src" / "__init__.py").write_text("", encoding="utf-8", newline="\n")
    (root / "src" / "shared.py").write_text(BASE, encoding="utf-8", newline="\n")
    (root / "tests" / "test_shared.py").write_text(TESTS, encoding="utf-8", newline="\n")
    return tmp_path / "fixtures"


async def _run(task: TaskDefinition, fixtures: Path, tmp_path: Path, run_id: str):
    return await execute_task(
        task,
        RunConfig(experiment_id="merge_probe", run_id=run_id, arm="C0", master_seed=SEED),
        workspace_root=tmp_path / run_id,
        fixtures_root=fixtures,
    )


DISJOINT = _edit('"c0"', '"c1"')  # gamma: separated from alpha by an untouched function
SAME_LINES = _edit('"a0"', '"a2"')  # alpha again, differently


class TestWinnerTakeAll:
    async def test_last_writer_loses_one_of_two_disjoint_edits(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        """The recorded limitation, reproduced: the same two edits, one lost."""
        result = await _run(
            _task(b_edit=DISJOINT, merge=ContestedMerge.LAST_WRITER), fixtures, tmp_path, "lw"
        )
        assert result.succeeded is False
        assert result.outcome.tests_passed is False
        assert result.merge_conflicts is None, "nothing merged, so nothing is known about conflicts"
        assert "merge_conflicts" not in result.to_dict()


class TestThreeWay:
    async def test_disjoint_edits_to_one_file_both_survive(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        result = await _run(
            _task(b_edit=DISJOINT, merge=ContestedMerge.THREE_WAY), fixtures, tmp_path, "tw"
        )
        assert result.merge_conflicts == []
        assert result.outcome.tests_passed is True
        assert result.succeeded is True
        assert "contested_merge_clean" in result.outcome.evidence
        assert result.to_dict()["merge_conflicts"] == []
        merged = (tmp_path / "tw" / "tw_integrated" / "src" / "shared.py").read_text("utf-8")
        assert '"a1"' in merged and '"c1"' in merged and "<<<<<<<" not in merged

    async def test_edits_to_the_same_lines_are_a_conflict_that_fails_the_run(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        result = await _run(
            _task(b_edit=SAME_LINES, merge=ContestedMerge.THREE_WAY),
            fixtures,
            tmp_path,
            "tw_conflict",
        )
        assert result.merge_conflicts == ["src/shared.py"]
        assert result.succeeded is False
        assert "contested_merge_conflict=src/shared.py" in result.outcome.evidence
        assert "did not merge cleanly" in result.outcome.detail
        merged = (
            tmp_path / "tw_conflict" / "tw_conflict_integrated" / "src" / "shared.py"
        ).read_text("utf-8")
        assert "<<<<<<< agent_a" in merged and ">>>>>>> agent_b" in merged

    async def test_a_conflict_fails_the_run_even_if_the_tests_would_pass(
        self, fixtures: Path, tmp_path: Path
    ) -> None:
        """A test that never imports the conflicted file must not turn an unmerged
        result into a pass: CooperBench's criterion is merge cleanly *and* pass."""
        task = _task(b_edit=SAME_LINES, merge=ContestedMerge.THREE_WAY)
        task = dataclasses.replace(
            task, success=dataclasses.replace(task.success, integration_test=("python", "-c", "0"))
        )
        result = await _run(task, fixtures, tmp_path, "tw_blind")
        assert result.outcome.tests_passed is True
        assert result.merge_conflicts == ["src/shared.py"]
        assert result.succeeded is False

    async def test_the_run_is_reproducible(self, fixtures: Path, tmp_path: Path) -> None:
        task = _task(b_edit=DISJOINT, merge=ContestedMerge.THREE_WAY)
        first = await _run(task, fixtures, tmp_path, "rep1")
        second = await _run(task, fixtures, tmp_path, "rep1_again")
        assert first.outcome.evidence == second.outcome.evidence
        assert first.workspace_digests == second.workspace_digests


class TestTheDefaultIsUntouched:
    def test_a_task_that_never_mentions_the_field_serialises_and_hashes_as_before(self) -> None:
        task = _task(b_edit=DISJOINT, merge=ContestedMerge.LAST_WRITER)
        assert "contested_merge" not in task.to_dict()
        assert (
            dataclasses.replace(task, contested_merge=ContestedMerge.THREE_WAY).content_hash()
            != task.content_hash()
        ), "the strategy changes what success means, so it must change the task hash"
        assert TaskDefinition.from_dict(task.to_dict()) == task
        three_way = dataclasses.replace(task, contested_merge=ContestedMerge.THREE_WAY)
        assert TaskDefinition.from_dict(three_way.to_dict()) == three_way

    def test_an_unknown_strategy_is_refused(self) -> None:
        from causalmesh.tasks.definition import TaskError

        with pytest.raises(TaskError, match="contested_merge"):
            _task(b_edit=DISJOINT, merge="newest_wins")
