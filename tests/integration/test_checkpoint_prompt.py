"""A person-attached checkpoint handler, through the real experiment loop.

`--checkpoint-prompt` installs `TerminalCheckpointHandler` as the run's
`checkpoint_handler`. The runner already records a refused checkpoint as
CHECKPOINT_DECIDED under the `checkpoint` identity; what this file pins is
that a handler object in the run config neither breaks the artifact nor
makes a human-decided run look reproducible.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from causalmesh.cli.commands_experiment import _attach_checkpoint_prompt
from causalmesh.experiments import plan_experiment, profile
from causalmesh.policy import TerminalCheckpointHandler
from causalmesh.scheduler import ExperimentRunner, RunEnvironment
from causalmesh.tasks import TaskDefinition

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[2]
SEED = b"causalmesh-checkpoint-prompt-01"


class AlwaysNo(io.StringIO):
    """A terminal whose person answers `no` to every question."""

    def readline(self, *args: Any) -> str:
        return "no\n"

    def isatty(self) -> bool:
        return True


class TestTheFlagOnlyActsWhenAPersonCanAnswer:
    def test_an_interactive_stdin_installs_the_terminal_handler(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdin", AlwaysNo())
        run_config: dict[str, Any] = {}
        _attach_checkpoint_prompt(run_config, has_checkpoints=True)
        assert isinstance(run_config["checkpoint_handler"], TerminalCheckpointHandler)

    def test_a_pipe_leaves_the_default_in_place(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("yes\nyes\n"))
        run_config: dict[str, Any] = {}
        _attach_checkpoint_prompt(run_config, has_checkpoints=True)
        assert "checkpoint_handler" not in run_config

    def test_a_contract_without_checkpoints_installs_nothing(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdin", AlwaysNo())
        run_config: dict[str, Any] = {}
        _attach_checkpoint_prompt(run_config, has_checkpoints=False)
        assert "checkpoint_handler" not in run_config

    def test_the_installed_handler_demands_a_terminal_itself(self, monkeypatch) -> None:
        monkeypatch.setattr(sys, "stdin", AlwaysNo())
        run_config: dict[str, Any] = {}
        _attach_checkpoint_prompt(run_config, has_checkpoints=True)
        handler = run_config["checkpoint_handler"]
        assert handler._require_tty is True

    def test_the_option_is_documented(self) -> None:
        from typer.testing import CliRunner

        from causalmesh.cli.main import app

        result = CliRunner().invoke(app, ["experiment", "run", "--help"])
        assert result.exit_code == 0
        assert "--checkpoint-prompt" in result.stdout


@pytest.mark.slow
async def test_a_run_with_the_handler_writes_a_truthful_artifact(tmp_path: Path) -> None:
    task = TaskDefinition.from_yaml(REPO / "tasks" / "schema_handler_widen.yaml")
    contract = tmp_path / "causalmesh.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "policy": {"arm": "C3", "checkpoints": [{"on": "path", "require": "human"}]},
            }
        ),
        encoding="utf-8",
    )
    handler = TerminalCheckpointHandler(
        input_stream=AlwaysNo(), output_stream=io.StringIO(), require_tty=True
    )
    plan = plan_experiment(
        experiment_id="exp_ckpt",
        profile=profile("smoke"),
        task_ids=[task.task_id],
        master_seed=SEED,
        task_hashes={task.task_id: task.content_hash()},
    )
    environment = RunEnvironment(
        fixtures_root=REPO / "fixtures",
        raw_root=tmp_path / "raw",
        workspace_root=tmp_path / "work",
        index_path=tmp_path / "raw" / "index.db",
    )
    with ExperimentRunner(
        plan=plan,
        tasks={task.task_id: task},
        environment=environment,
        master_seed=SEED,
        run_config={"contract_path": str(contract), "checkpoint_handler": handler},
    ) as runner:
        runner.prepare()
        report = await runner.run()
    assert report.is_complete, report.errors

    artifacts = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((tmp_path / "raw").glob("*/run.json"))
    ]
    assert len(artifacts) == len(plan)
    for artifact in artifacts:
        assert artifact["provenance"]["checkpoint_handler"] == "TerminalCheckpointHandler"
        assert artifact["reproducible"] is False
        assert isinstance(artifact["checkpoint_decisions"], list)

    # Every decision belongs to exactly one run, none is dropped or counted twice.
    assert sum(len(a["checkpoint_decisions"]) for a in artifacts) == len(handler.decisions())
    assert handler.decisions(), "the contract's checkpoint never reached the handler"

    c3 = [a for a in artifacts if a["arm"] == "C3"]
    assert c3
    decided = [
        record["event"]
        for record in c3[0]["chain"]
        if record["event"]["event_type"] == "CHECKPOINT_DECIDED"
    ]
    assert decided, "a refused checkpoint must reach the chain on the enforcing arm"
    assert {event["identity"]["agent_id"] for event in decided} == {"checkpoint"}
