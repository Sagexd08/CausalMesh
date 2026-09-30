"""`causalmesh policy validate`, found the way a developer runs it: with no path.

`validate` is documented to check the Phase 1 SDK sections (`agent:` and
`tools:`) as well as the core contract. With an explicit path it did. Run
bare, it located the file by parsing it with the strict core loader, which
rejects those two keys, so the shipped `examples/causalmesh.yaml` crashed the
command with a raw traceback. Nothing tested the command at all.

These tests run the real command through typer's runner and assert on exit
codes and the JSON a script would consume, not on the wording of the tables.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.cli._output import Exit
from causalmesh.cli.main import app

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
runner = CliRunner()

SDK_CONTRACT = """\
version: 1
agent:
  id: coding-agent
roles:
  - agent_id: coding-agent
    archetype: writer
    owns: [src/]
tools:
  write_file:
    mode: auto
policy:
  arm: C3
"""


def validate(*args: str):
    return runner.invoke(app, ["policy", "validate", "--json", *args])


class TestDefaultDiscovery:
    def test_a_contract_with_sdk_sections_validates_without_a_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "causalmesh.yaml").write_text(SDK_CONTRACT, encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = validate()

        assert result.exit_code == Exit.OK, result.output
        assert result.exception is None
        body = json.loads(result.stdout)
        assert body["valid"] is True
        assert body["sdk_agent_id"] == "coding-agent"
        assert body["sdk_tools"] == ["write_file"]

    def test_the_contract_is_found_in_a_parent_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "causalmesh.yaml").write_text(SDK_CONTRACT, encoding="utf-8")
        nested = tmp_path / "src" / "deep"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        result = validate()

        assert result.exit_code == Exit.OK, result.output
        assert json.loads(result.stdout)["source"] == str(tmp_path / "causalmesh.yaml")

    def test_the_repositorys_own_sdk_example_validates_from_its_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(REPO / "examples")

        result = validate()

        assert result.exit_code == Exit.OK, result.output
        assert json.loads(result.stdout)["valid"] is True

    def test_no_contract_anywhere_is_a_usage_error_not_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["policy", "validate"])

        assert result.exit_code == Exit.USAGE
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "no causalmesh.yaml" in result.output

    def test_an_invalid_contract_is_reported_not_raised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nrolez:\n  - agent_id: a\n", encoding="utf-8"
        )
        monkeypatch.chdir(tmp_path)

        result = validate()

        assert result.exit_code == Exit.FAILED, result.output
        assert result.exception is None or isinstance(result.exception, SystemExit)
        body = json.loads(result.stdout)
        assert body["valid"] is False
        assert "rolez" in body["error"]


class TestExplicitPath:
    def test_an_explicit_path_still_validates_sdk_sections(self, tmp_path: Path) -> None:
        path = tmp_path / "custom.yaml"
        path.write_text(SDK_CONTRACT, encoding="utf-8")

        result = validate(str(path))

        assert result.exit_code == Exit.OK, result.output
        assert json.loads(result.stdout)["valid"] is True
