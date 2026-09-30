"""One contract schema: every command that reads `causalmesh.yaml` accepts the same file.

`policy validate` and `CausalMesh.from_config` used to accept the SDK-only
`agent:` and `tools:` sections while `policy show`, `policy check` and `serve`
rejected them with exit 2, so one file could be valid for one command and a
usage error for the next. The typo guard on unknown top-level keys must
survive that: a key nothing reads is a rule that does not exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
import uvicorn
from typer.testing import CliRunner

from causalmesh import CausalMesh
from causalmesh.cli.main import app
from causalmesh.policy.contract import Contract, ContractError

pytestmark = [pytest.mark.integration]

runner = CliRunner()

SDK_CONTRACT = """\
version: 1
agent:
  id: coder
tools:
  write_file:
    mode: auto
  read_file:
roles:
  - agent_id: coder
    owns:
      - src/
policy:
  arm: C3
evidence:
  sign: false
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "causalmesh.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def no_listen(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    apps: list[Any] = []
    monkeypatch.setattr(uvicorn, "run", lambda application, **_: apps.append(application))
    return apps


def _commands(tmp_path: Path) -> dict[str, list[str]]:
    return {
        "policy show": ["policy", "show", "--root", str(tmp_path)],
        "policy check": [
            "policy",
            "check",
            "--root",
            str(tmp_path),
            "--agent",
            "coder",
            "--name",
            "src/a.py",
        ],
        "policy validate": ["policy", "validate", str(tmp_path / "causalmesh.yaml")],
        "serve": ["serve", "--root", str(tmp_path), "--dev"],
    }


class TestTheSameFileEverywhere:
    @pytest.mark.parametrize("command", ["policy show", "policy check", "policy validate", "serve"])
    def test_a_contract_with_sdk_sections_is_accepted(
        self, tmp_path: Path, no_listen: list[Any], command: str
    ) -> None:
        _write(tmp_path, SDK_CONTRACT)
        result = runner.invoke(app, _commands(tmp_path)[command])
        assert result.exit_code == 0, f"{command}: {result.output}"

    def test_the_library_loaders_accept_it_too(self, tmp_path: Path) -> None:
        path = _write(tmp_path, SDK_CONTRACT)
        assert Contract.load(path).roles[0].agent_id == "coder"
        assert Contract.find(tmp_path) is not None
        assert CausalMesh.from_config(path).agent_id == "coder"

    def test_the_gate_builds_the_same_contract_with_or_without_the_sdk_sections(
        self, tmp_path: Path
    ) -> None:
        with_sdk = _write(tmp_path, SDK_CONTRACT)
        without = tmp_path / "plain.yaml"
        without.write_text(
            "".join(
                line
                for line in SDK_CONTRACT.splitlines(keepends=True)
                if not line.startswith(("agent:", "  id:", "tools:", "  write_file", "  read_file"))
                and "mode: auto" not in line
            ),
            encoding="utf-8",
        )
        # The gate reads neither section, so the contract it builds is identical.
        left = Contract.load(with_sdk).to_dict()
        right = Contract.load(without).to_dict()
        assert left == right


class TestTyposAreStillRejectedEverywhere:
    @pytest.mark.parametrize(
        "bad",
        [
            "tols:\n  write_file:\n",  # a misspelt top-level key
            "agnet:\n  id: coder\n",
            "polcy:\n  arm: C3\n",
        ],
    )
    @pytest.mark.parametrize("command", ["policy show", "policy check", "policy validate", "serve"])
    def test_a_misspelt_top_level_key_is_rejected(
        self, tmp_path: Path, no_listen: list[Any], command: str, bad: str
    ) -> None:
        _write(tmp_path, SDK_CONTRACT + bad)
        result = runner.invoke(app, _commands(tmp_path)[command])
        assert result.exit_code != 0, f"{command} accepted a misspelt key"
        assert no_listen == [], "the server started on a misspelt contract"
        assert "unknown key" in result.output

    @pytest.mark.parametrize(
        ("bad", "needle"),
        [
            ("agent:\n  idd: x\n", "agent"),
            ("agent: [a]\n", "agent"),
            ("tools:\n  t:\n    mdoe: auto\n", "tools.t"),
            ("tools:\n  t:\n    mode: manual\n", "mode"),
            ("tools: [a]\n", "tools"),
        ],
    )
    def test_a_bad_sdk_section_is_rejected_by_the_core_loader(
        self, tmp_path: Path, bad: str, needle: str
    ) -> None:
        path = _write(tmp_path, f"version: 1\n{bad}")
        with pytest.raises(ContractError, match=needle):
            Contract.load(path)
        result = runner.invoke(app, ["policy", "show", "--root", str(tmp_path)])
        assert result.exit_code == 2
        assert needle in result.output
