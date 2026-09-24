"""`causalmesh init` and `causalmesh quickstart` (spec: fewer steps to a

first verified run).

`init` is tested for real content, not just a zero exit code: a starter
contract that a person cannot actually use is a command that "succeeded"
at nothing. `quickstart` is tested end to end against this repository's
real fixtures and tasks -- the same real run `causalmesh experiment run`
would produce, just chained.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from causalmesh.cli.main import app
from causalmesh.policy.contract import Contract

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args))


class TestInit:
    def test_writes_a_contract_that_parses(self, tmp_path: Path) -> None:
        result = invoke("init", "--root", str(tmp_path))
        assert result.exit_code == 0, result.stdout
        contract = Contract.load(tmp_path / "causalmesh.yaml")
        assert contract.version == 1

    def test_reads_roles_from_an_existing_agents_md(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text(
            "# AGENTS.md\n\n"
            "## Layout\n\n"
            "| Path | What lives there |\n"
            "|---|---|\n"
            "| `src/` | the code |\n"
            "| `docs/` | the documentation |\n",
            encoding="utf-8",
        )
        result = invoke("init", "--root", str(tmp_path))
        assert result.exit_code == 0, result.stdout
        contract = Contract.load(tmp_path / "causalmesh.yaml")
        role_ids = {role.agent_id for role in contract.roles}
        assert "docs" in role_ids
        assert contract.owner_of("docs/backlog.md") == "docs"

    def test_falls_back_to_the_empty_template_with_no_agents_md(self, tmp_path: Path) -> None:
        result = invoke("init", "--root", str(tmp_path))
        assert result.exit_code == 0, result.stdout
        contract = Contract.load(tmp_path / "causalmesh.yaml")
        assert [role.agent_id for role in contract.roles] == ["agent_a"]

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path) -> None:
        invoke("init", "--root", str(tmp_path))
        result = invoke("init", "--root", str(tmp_path))
        assert result.exit_code == 2

    def test_force_overwrites(self, tmp_path: Path) -> None:
        invoke("init", "--root", str(tmp_path))
        result = invoke("init", "--root", str(tmp_path), "--force")
        assert result.exit_code == 0, result.stdout

    def test_the_generated_contract_is_permissive(self, tmp_path: Path) -> None:
        (tmp_path / "AGENTS.md").write_text(
            "| Path | What lives there |\n|---|---|\n| `src/` | code |\n", encoding="utf-8"
        )
        result = invoke("init", "--root", str(tmp_path))
        assert result.exit_code == 0, result.stdout
        raw = yaml.safe_load((tmp_path / "causalmesh.yaml").read_text(encoding="utf-8"))
        assert raw["policy"]["contested"] == {}
        assert raw["policy"]["budgets"] == {}

    def test_top_level_init_matches_policy_init(self, tmp_path: Path) -> None:
        """The top-level alias calls the same command `policy init` does,

        not a parallel implementation that could drift from it.
        """
        top_level = invoke("init", "--root", str(tmp_path / "a"))
        nested = invoke("policy", "init", "--root", str(tmp_path / "b"))
        assert top_level.exit_code == nested.exit_code == 0
        contract_a = Contract.load(tmp_path / "a" / "causalmesh.yaml")
        contract_b = Contract.load(tmp_path / "b" / "causalmesh.yaml")
        assert contract_a.to_dict() == contract_b.to_dict()


@pytest.mark.slow
class TestQuickstartEndToEnd:
    """Real subprocess-driving runs against this repository's own fixtures

    and tasks -- the same class of test `TestContractDiscovery` already
    runs for `experiment run` alone.
    """

    def test_a_full_cycle_against_this_repository(self) -> None:
        experiment_id = "quickstart_cli_test"
        raw_dir = REPO / "data" / "raw" / experiment_id
        try:
            result = invoke(
                "quickstart", "--root", str(REPO), "--profile", "smoke", "--id", experiment_id
            )
            assert result.exit_code == 0, result.stdout
            assert "quickstart complete" in result.stdout
        finally:
            import shutil

            if raw_dir.is_dir():
                shutil.rmtree(raw_dir, ignore_errors=True)
            index_path = REPO / "data" / f"{experiment_id}.index.db"
            index_path.unlink(missing_ok=True)

    def test_skips_init_when_a_contract_already_exists(self) -> None:
        """This repository's own causalmesh.yaml must survive a quickstart

        run against it -- quickstart must never silently overwrite a real
        operator's contract.
        """
        contract_path = REPO / "causalmesh.yaml"
        before = contract_path.read_text(encoding="utf-8")
        experiment_id = "quickstart_cli_test_2"
        raw_dir = REPO / "data" / "raw" / experiment_id
        try:
            result = invoke(
                "quickstart", "--root", str(REPO), "--profile", "smoke", "--id", experiment_id
            )
            assert result.exit_code == 0, result.stdout
            assert "already exists; skipping init" in result.stdout
            assert contract_path.read_text(encoding="utf-8") == before
        finally:
            import shutil

            if raw_dir.is_dir():
                shutil.rmtree(raw_dir, ignore_errors=True)
            index_path = REPO / "data" / f"{experiment_id}.index.db"
            index_path.unlink(missing_ok=True)
