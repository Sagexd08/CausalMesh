"""Unit tests for reading causal edges back out of run artifacts.

`edges/report.py` is a read path, not a store: it reads `result.edges`
straight off `run.json` the way `metrics.accounting._read_run` reads costs,
so these tests focus on the two things a read path can get wrong — a
missing or absent field read as an error instead of "none recorded", and a
malformed record passed through instead of being rejected.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from causalmesh.edges import (
    CausalEdge,
    EdgeReportError,
    RelationshipType,
    collect_edges,
    count_by_relationship,
    edges_for_run,
    run_edges_to_dict,
    total_edges,
)

pytestmark = pytest.mark.unit


def _write_artifact(run_dir: Path, *, edges: list[dict] | None = None, **overrides) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "arm": "C3",
        "run_id": run_dir.name,
        "task_id": "concurrent_edit_collision",
        "edges": edges if edges is not None else [],
    }
    result.update(overrides)
    artifact = {"arm": result["arm"], "result": result}
    (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")


class TestEdgesForRun:
    def test_a_run_with_no_edges_key_reads_as_none_recorded(self, tmp_path: Path) -> None:
        # An artifact from before this feature shipped has no "edges" key at
        # all. That is a fact about when it ran, not an error.
        run_dir = tmp_path / "run_0000"
        run_dir.mkdir()
        artifact = {"arm": "C3", "result": {"run_id": "run_0000", "task_id": "t1"}}
        (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")

        run_edges = edges_for_run(run_dir)

        assert run_edges.edges == ()
        # ...and the emptiness is unknown, not zero: the artifact cannot say
        # the run had no relationships, only that it never recorded any.
        assert run_edges.recorded is False

    def test_a_run_with_an_empty_edges_list_recorded_a_real_zero(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path / "run_0000", edges=[])

        assert edges_for_run(tmp_path / "run_0000").recorded is True

    def test_a_non_list_edges_value_is_a_located_error(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path / "run_bad", edges="nope")  # type: ignore[arg-type]

        with pytest.raises(EdgeReportError):
            edges_for_run(tmp_path / "run_bad")

    def test_a_run_with_real_edges_reads_them_back(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_0001"
        edge = CausalEdge(
            from_event_id="evt_agent_b_0002",
            to_event_id="run_0001_verdict_1",
            relationship=RelationshipType.REQUIRED,
        )
        _write_artifact(run_dir, edges=[edge.to_dict()])

        run_edges = edges_for_run(run_dir)

        assert run_edges.edges == (edge,)
        assert run_edges.run_id == "run_0001"
        assert run_edges.arm == "C3"
        assert run_edges.task_id == "concurrent_edit_collision"

    def test_a_missing_artifact_is_a_located_error(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_missing"
        run_dir.mkdir()

        with pytest.raises(EdgeReportError):
            edges_for_run(run_dir)

    def test_a_malformed_edge_record_is_a_located_error(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_bad"
        # Missing "relationship" -- CausalEdge.from_dict must reject this
        # rather than silently dropping the field or guessing a default.
        _write_artifact(run_dir, edges=[{"from_event_id": "a", "to_event_id": "b"}])

        with pytest.raises(EdgeReportError):
            edges_for_run(run_dir)


class TestCollectEdges:
    def test_collects_every_run_in_order(self, tmp_path: Path) -> None:
        edge = CausalEdge(
            from_event_id="evt_1", to_event_id="evt_2", relationship=RelationshipType.CAUSED
        )
        _write_artifact(tmp_path / "run_0000", edges=[])
        _write_artifact(tmp_path / "run_0001", edges=[edge.to_dict()])

        runs = collect_edges(tmp_path)

        assert [r.run_id for r in runs] == ["run_0000", "run_0001"]
        assert runs[0].edges == ()
        assert runs[1].edges == (edge,)

    def test_an_empty_directory_is_a_located_error(self, tmp_path: Path) -> None:
        with pytest.raises(EdgeReportError):
            collect_edges(tmp_path)

    def test_a_missing_directory_is_a_located_error(self, tmp_path: Path) -> None:
        with pytest.raises(EdgeReportError):
            collect_edges(tmp_path / "does_not_exist")


class TestRunEdgesToDict:
    def test_serializes_every_edge(self, tmp_path: Path) -> None:
        edge = CausalEdge(
            from_event_id="evt_1", to_event_id="evt_2", relationship=RelationshipType.REQUIRED
        )
        _write_artifact(tmp_path / "run_0000", edges=[edge.to_dict()])
        run_edges = edges_for_run(tmp_path / "run_0000")

        payload = run_edges_to_dict(run_edges)

        assert payload["run_id"] == "run_0000"
        assert payload["edges_recorded"] is True
        assert payload["edge_count"] == 1
        (serialized,) = payload["edges"]
        for key, value in edge.to_dict().items():
            assert serialized[key] == value
        # No chain in this artifact, so nothing was checked: unknown, not a
        # guess and not "unresolved".
        assert serialized["from_label"] == "unknown"
        assert serialized["to_label"] == "unknown"


def _record(event_id: str, event_type: str, agent_id: str, payload: dict) -> dict:
    return {
        "event": {
            "event_id": event_id,
            "event_type": event_type,
            "identity": {"agent_id": agent_id},
            "payload": payload,
        }
    }


class TestPredatesEdges:
    """An artifact with no `edges` key is unknown, and never contributes a 0."""

    def _older(self, run_dir: Path) -> None:
        run_dir.mkdir(parents=True)
        artifact = {"arm": "C2", "result": {"run_id": run_dir.name, "task_id": "t"}}
        (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")

    def test_the_payload_says_null_not_empty(self, tmp_path: Path) -> None:
        self._older(tmp_path / "run_old")

        payload = run_edges_to_dict(edges_for_run(tmp_path / "run_old"))

        assert payload["edges_recorded"] is False
        assert payload["edges"] is None
        assert payload["edge_count"] is None

    def test_counts_over_only_older_runs_are_unknown(self, tmp_path: Path) -> None:
        self._older(tmp_path / "run_old")
        runs = collect_edges(tmp_path)

        assert total_edges(runs) is None
        assert count_by_relationship(runs) is None

    def test_an_older_run_adds_nothing_to_a_known_count(self, tmp_path: Path) -> None:
        self._older(tmp_path / "run_0")
        edge = CausalEdge(from_event_id="a", to_event_id="b", relationship=RelationshipType.CAUSED)
        _write_artifact(tmp_path / "run_1", edges=[edge.to_dict()])
        runs = collect_edges(tmp_path)

        assert total_edges(runs) == 1


class TestCountByRelationship:
    def test_every_kind_is_present_with_a_real_zero(self, tmp_path: Path) -> None:
        edge = CausalEdge(
            from_event_id="a", to_event_id="b", relationship=RelationshipType.REQUIRED
        )
        _write_artifact(tmp_path / "run_0", edges=[edge.to_dict(), edge.to_dict()])
        counts = count_by_relationship(collect_edges(tmp_path))

        assert counts == {"CAUSED": 0, "REQUIRED": 2, "RECOVERED": 0, "SUPERSEDED": 0}

    def test_known_runs_with_no_edges_count_zero_not_unknown(self, tmp_path: Path) -> None:
        _write_artifact(tmp_path / "run_0", edges=[])
        runs = collect_edges(tmp_path)

        assert total_edges(runs) == 0
        assert set(count_by_relationship(runs).values()) == {0}


class TestLabels:
    def _run_with_chain(self, tmp_path: Path) -> Path:
        run_dir = tmp_path / "run_0"
        run_dir.mkdir()
        chain = [
            _record("evt_b_2", "FAILURE", "agent_b", {"outcome": "denied"}),
            _record(
                "run_0_verdict_0",
                "POLICY_VERDICT",
                "policy_gate",
                {"allowed": False, "rule": "ownership"},
            ),
            _record(
                "run_0_integration_test",
                "INTEGRATION_TEST_RESULT",
                "integration_test",
                {"exit_code": 1},
            ),
            _record("run_0_acceptance", "ACCEPTANCE_DECIDED", "acceptance", {"verdict": "REJECT"}),
            _record("evt_odd", "FAILURE", "agent_a", {"outcome": "caf\u00e9"}),
        ]
        edges = [
            CausalEdge("evt_b_2", "run_0_verdict_0", RelationshipType.REQUIRED).to_dict(),
            CausalEdge(
                "run_0_acceptance", "run_0_integration_test", RelationshipType.REQUIRED
            ).to_dict(),
            CausalEdge("evt_b_2", "evt_missing", RelationshipType.CAUSED).to_dict(),
        ]
        artifact = {
            "arm": "C3",
            "chain": chain,
            "result": {"run_id": "run_0", "task_id": "t", "edges": edges},
        }
        (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")
        return run_dir

    def test_ids_resolve_to_a_label_naming_the_event(self, tmp_path: Path) -> None:
        run = edges_for_run(self._run_with_chain(tmp_path))

        assert run.label_for("evt_b_2") == "FAILURE by agent_b, denied"
        assert (
            run.label_for("run_0_verdict_0")
            == "POLICY_VERDICT by policy_gate, refused, rule ownership"
        )
        assert run.label_for("run_0_acceptance") == "ACCEPTANCE_DECIDED by acceptance, REJECT"
        assert run.label_for("run_0_integration_test") == (
            "INTEGRATION_TEST_RESULT by integration_test, exit code 1"
        )

    def test_an_id_the_chain_lacks_is_unresolved_not_unknown(self, tmp_path: Path) -> None:
        run = edges_for_run(self._run_with_chain(tmp_path))

        assert run.label_for("evt_missing") == "unresolved"

    def test_a_missing_exit_code_reads_unknown_not_zero(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run_0"
        run_dir.mkdir()
        artifact = {
            "chain": [
                _record("t1", "INTEGRATION_TEST_RESULT", "integration_test", {"exit_code": None})
            ],
            "result": {"run_id": "run_0", "edges": []},
        }
        (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")

        assert edges_for_run(run_dir).label_for("t1").endswith("exit code unknown")

    def test_labels_are_ascii(self, tmp_path: Path) -> None:
        run = edges_for_run(self._run_with_chain(tmp_path))

        label = run.label_for("evt_odd")
        assert label.isascii()
        assert "caf" in label
