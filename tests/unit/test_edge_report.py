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
    edges_for_run,
    run_edges_to_dict,
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
        assert payload["edges"] == [edge.to_dict()]
