"""`causalmesh analyze --edges`: the query-facing view of a collection's edges.

The facts this surface must show, rather than how it lays them out
(AGENTS.md, "Testing"): counts by kind, each edge's endpoints with a label
that resolves against the artifact's chain, and `unknown` (never 0) for a
run that predates edges. Collections are built in `tmp_path` and passed
with `--root`, so nothing touches `data/raw/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.cli.main import app
from causalmesh.edges import CausalEdge, RelationshipType

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wide_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render wide, so Rich does not truncate an id and hide it from a check.

    The tests assert the facts on screen, not the layout; a fixed narrow
    default width would make them assert the terminal size instead.
    """
    from causalmesh.cli._output import out_console

    monkeypatch.setattr(out_console, "_width", 240)


def _checkout(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "fixtures").mkdir()
    return tmp_path


def _event(event_id: str, event_type: str, agent_id: str, payload: dict) -> dict:
    return {
        "event": {
            "event_id": event_id,
            "event_type": event_type,
            "identity": {"agent_id": agent_id},
            "payload": payload,
        }
    }


def _write_run(root: Path, run: str, *, edges: list[dict] | None, chain: bool = True) -> None:
    run_dir = root / "data" / "raw" / "exp" / run
    run_dir.mkdir(parents=True)
    result: dict = {"run_id": run, "task_id": "t1"}
    if edges is not None:
        result["edges"] = edges
    artifact: dict = {"arm": "C3", "result": result}
    if chain:
        artifact["chain"] = [
            _event(f"{run}_acceptance", "ACCEPTANCE_DECIDED", "acceptance", {"verdict": "ACCEPT"}),
            _event(
                f"{run}_integration_test",
                "INTEGRATION_TEST_RESULT",
                "integration_test",
                {"exit_code": 0},
            ),
        ]
    (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")


def _acceptance_edge(run: str) -> dict:
    return CausalEdge(
        from_event_id=f"{run}_acceptance",
        to_event_id=f"{run}_integration_test",
        relationship=RelationshipType.REQUIRED,
    ).to_dict()


def _invoke(root: Path, *extra: str):
    return runner.invoke(app, ["analyze", "--edges", "--id", "exp", "--root", str(root), *extra])


class TestJson:
    def test_reports_counts_by_kind_and_labelled_endpoints(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[_acceptance_edge("r0")])
        _write_run(root, "r1", edges=[_acceptance_edge("r1")])

        result = _invoke(root, "--json")

        assert result.exit_code == 0, result.stdout
        report = json.loads(result.stdout)
        assert report["total_edges"] == 2
        assert report["by_relationship"]["REQUIRED"] == 2
        assert report["by_relationship"]["CAUSED"] == 0
        assert report["runs_edges_unknown"] == 0
        edge = report["runs"][0]["edges"][0]
        assert edge["from_event_id"] == "r0_acceptance"
        assert edge["to_event_id"] == "r0_integration_test"
        assert edge["from_label"] == "ACCEPTANCE_DECIDED by acceptance, ACCEPT"
        assert edge["to_label"] == "INTEGRATION_TEST_RESULT by integration_test, exit code 0"

    def test_carries_the_pilot_label(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[])

        report = json.loads(_invoke(root, "--json").stdout)

        assert report["label"] == "PILOT"

    def test_a_collection_predating_edges_is_unknown_not_zero(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=None)
        _write_run(root, "r1", edges=None)

        result = _invoke(root, "--json")

        assert result.exit_code == 0, result.stdout
        report = json.loads(result.stdout)
        assert report["total_edges"] is None
        assert report["by_relationship"] is None
        assert report["runs_with_edges"] is None
        assert report["runs_edges_unknown"] == 2
        assert report["total_runs"] == 2
        for run in report["runs"]:
            assert run["edges_recorded"] is False
            assert run["edges"] is None
            assert run["edge_count"] is None

    def test_a_mixed_collection_counts_only_what_was_recorded(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=None)
        _write_run(root, "r1", edges=[_acceptance_edge("r1")])

        report = json.loads(_invoke(root, "--json").stdout)

        assert report["total_edges"] == 1
        assert report["runs_edges_unknown"] == 1
        assert report["runs_with_edges"] == 1

    def test_a_run_that_recorded_no_edges_is_a_real_zero(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[])

        report = json.loads(_invoke(root, "--json").stdout)

        assert report["total_edges"] == 0
        assert report["runs_with_edges"] == 0
        assert report["runs"][0]["edges"] == []

    def test_an_endpoint_absent_from_the_chain_is_unresolved(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        dangling = CausalEdge("r0_acceptance", "r0_gone", RelationshipType.CAUSED).to_dict()
        _write_run(root, "r0", edges=[dangling])

        edge = json.loads(_invoke(root, "--json").stdout)["runs"][0]["edges"][0]

        assert edge["to_label"] == "unresolved"

    def test_an_artifact_with_no_chain_labels_endpoints_unknown(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[_acceptance_edge("r0")], chain=False)

        edge = json.loads(_invoke(root, "--json").stdout)["runs"][0]["edges"][0]

        assert edge["from_label"] == "unknown"
        assert edge["to_label"] == "unknown"

    def test_a_malformed_edge_is_an_error_exit(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[{"from_event_id": "a"}])

        result = _invoke(root, "--json")

        assert result.exit_code == 3


class TestTable:
    def test_shows_kinds_ids_labels_and_the_labels_of_the_tables(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[_acceptance_edge("r0")])

        result = _invoke(root)

        assert result.exit_code == 0, result.output
        for fact in (
            "REQUIRED",
            "CAUSED",
            "r0_acceptance",
            "r0_integration_test",
            "ACCEPTANCE_DECIDED",
            "INTEGRATION_TEST_RESULT",
            "DERIVED",
            "PILOT",
        ):
            assert fact in result.output

    def test_an_older_collection_says_unknown(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=None)

        result = _invoke(root)

        assert result.exit_code == 0, result.output
        assert "unknown" in result.output
        assert "predate" in result.output

    def test_output_is_ascii(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        _write_run(root, "r0", edges=[_acceptance_edge("r0")])
        _write_run(root, "r1", edges=None)

        result = _invoke(root)

        assert result.exit_code == 0, result.output
        # Rich draws its table borders with box-drawing characters and falls
        # back to ASCII on a console that cannot encode them; everything this
        # command adds to a cell must be ASCII either way.
        stray = [c for c in result.output if not c.isascii() and not "\u2500" <= c <= "\u257f"]
        assert stray == []

    def test_a_non_ascii_label_is_escaped_not_printed(self, tmp_path: Path) -> None:
        root = _checkout(tmp_path)
        edge = CausalEdge("r0_acceptance", "r0_odd", RelationshipType.CAUSED).to_dict()
        _write_run(root, "r0", edges=[edge])
        path = root / "data" / "raw" / "exp" / "r0" / "run.json"
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["chain"].append(_event("r0_odd", "FAILURE", "agent_a", {"outcome": "caf\u00e9"}))
        path.write_text(json.dumps(artifact), encoding="utf-8")

        result = _invoke(root)

        assert result.exit_code == 0, result.output
        assert "caf\\xe9" in result.output
        assert "\u00e9" not in result.output
