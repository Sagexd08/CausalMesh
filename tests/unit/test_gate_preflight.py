"""The sec 37 gate must not read "no test runner" as "the arms do not differ".

`python -m pytest` with no pytest installed exits 1, the same code as a failed
test, so every arm fails identically and the gate says NOT SENSITIVE. The
preflight asks the harness's own interpreter whether the command can run at
all, and the gate reports COULD NOT RUN instead of a verdict it did not earn.
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

from causalmesh.tasks import (
    SensitivityReport,
    TaskDefinition,
    check_sensitivity,
    runner as task_runner,
)
from causalmesh.tasks.runner import integration_test_preflight

pytestmark = pytest.mark.unit

TASK_PATH = Path(__file__).resolve().parents[2] / "tasks" / "schema_handler_widen.yaml"


def _task_running(*command: str) -> TaskDefinition:
    task = TaskDefinition.from_yaml(TASK_PATH)
    return dataclasses.replace(
        task, success=dataclasses.replace(task.success, integration_test=command)
    )


class TestPreflight:
    def test_a_runnable_module_command_passes(self) -> None:
        # `json` is stdlib, so this proves the probe says yes without needing pytest.
        assert integration_test_preflight(_task_running(sys.executable, "-m", "json.tool")) is None

    def test_a_module_the_interpreter_cannot_import_is_named(self) -> None:
        problem = integration_test_preflight(
            _task_running(sys.executable, "-m", "no_such_module_for_preflight", "-q")
        )
        assert problem is not None
        assert "no_such_module_for_preflight" in problem

    def test_a_missing_executable_is_named(self) -> None:
        problem = integration_test_preflight(_task_running("no-such-binary-for-preflight"))
        assert problem is not None
        assert "no-such-binary-for-preflight" in problem

    def test_a_command_shape_it_cannot_probe_is_assumed_runnable(self) -> None:
        """The check claims only what it knows: a plain script path is not probed."""
        assert integration_test_preflight(_task_running(sys.executable, "-c", "pass")) is None

    def test_it_asks_the_harness_environment_not_this_process(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The test runs under a scrubbed environment; an executable that is on
        this process's PATH but not the harness's must be reported."""
        (tmp_path / "only-on-this-path").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (tmp_path / "only-on-this-path").chmod(0o755)
        monkeypatch.setattr(
            task_runner,
            "_harness_environment",
            lambda: {"PATH": str(tmp_path / "somewhere-else")},
        )
        monkeypatch.setenv("PATH", str(tmp_path))
        assert integration_test_preflight(_task_running("only-on-this-path")) is not None


class TestTheGateReportsItCouldNotRun:
    async def test_no_arm_is_run_and_the_reason_is_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        async def must_not_run(*args: object, **kwargs: object) -> None:
            raise AssertionError("the gate ran an arm although its test runner is missing")

        monkeypatch.setattr(task_runner, "execute_task", must_not_run)
        report = await check_sensitivity(
            _task_running(sys.executable, "-m", "no_such_module_for_preflight"),
            workspace_root=tmp_path / "ws",
            fixtures_root=Path(__file__).resolve().parents[2] / "fixtures",
            master_seed=b"gate-preflight-seed-0000000000001",
        )
        assert report.could_not_run
        assert report.sensitive is False
        assert "COULD NOT RUN" in report.summary()
        assert "NOT SENSITIVE" not in report.summary()
        assert report.to_dict()["could_not_run"] == report.could_not_run
        assert not (tmp_path / "ws").exists()


class TestTheReportShapeIsUnchangedWhenTheGateRan:
    def test_an_ordinary_report_has_no_could_not_run_key(self) -> None:
        report = SensitivityReport(
            task_id="t", isolated_successes=0, informed_successes=1, repetitions=1
        )
        assert "could_not_run" not in report.to_dict()
        assert report.sensitive is True
        assert report.summary().startswith("t: SENSITIVE")
