"""Unit tests for causal edges (`docs/backlog.md`, "Causal edges over the chain").

Three things get the most attention:

- **The store never mutates.** Like `ChainStore`, `EdgeStore` offers append
  and readers only — an edge log that could be silently corrected would
  undermine the same "recorded evidence, not a log line" property the chain
  itself is built around.
- **Edges are decoupled from any one chain.** The store and query surface
  must work over edges referencing event ids they have never independently
  verified — cross-checking against a chain is a caller's job, not this
  layer's.
- **The vocabulary matches the backlog exactly.** `CAUSED`, `REQUIRED`,
  `RECOVERED`, `SUPERSEDED` are the four relationship kinds the backlog entry
  names; nothing here should silently drift from that list.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from causalmesh.edges import (
    CausalEdge,
    EdgeIndex,
    EdgeStore,
    EdgeStoreError,
    EdgeValidationError,
    RelationshipType,
    load_edges,
)

pytestmark = pytest.mark.unit


class TestRelationshipType:
    def test_the_vocabulary_matches_the_backlog_entry(self) -> None:
        # docs/backlog.md names exactly these four kinds. A fifth appearing
        # here without the backlog being updated would be undocumented scope
        # creep; one going missing would silently break callers.
        assert {str(r) for r in RelationshipType} == {
            "CAUSED",
            "REQUIRED",
            "RECOVERED",
            "SUPERSEDED",
        }


class TestCausalEdgeConstruction:
    def test_a_well_formed_edge_round_trips_through_a_dict(self) -> None:
        edge = CausalEdge(
            from_event_id="evt_write_0007",
            to_event_id="evt_decision_0003",
            relationship=RelationshipType.CAUSED,
            note="acceptance decision authorized the write",
        )
        rebuilt = CausalEdge.from_dict(edge.to_dict())
        assert rebuilt == edge

    def test_note_defaults_to_empty_string(self) -> None:
        edge = CausalEdge(
            from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.REQUIRED
        )
        assert edge.note == ""

    def test_an_edge_cannot_relate_an_event_to_itself(self) -> None:
        with pytest.raises(EdgeValidationError, match="itself"):
            CausalEdge(
                from_event_id="evt_a", to_event_id="evt_a", relationship=RelationshipType.CAUSED
            )

    def test_a_malformed_event_id_is_rejected(self) -> None:
        with pytest.raises(EdgeValidationError):
            CausalEdge(
                from_event_id="not an identifier!",
                to_event_id="evt_b",
                relationship=RelationshipType.CAUSED,
            )

    def test_relationship_must_be_a_relationship_type(self) -> None:
        with pytest.raises(EdgeValidationError, match="RelationshipType"):
            CausalEdge(from_event_id="evt_a", to_event_id="evt_b", relationship="CAUSED")  # type: ignore[arg-type]

    def test_from_dict_rejects_a_missing_field(self) -> None:
        with pytest.raises(EdgeValidationError, match="missing field"):
            CausalEdge.from_dict({"from_event_id": "evt_a", "to_event_id": "evt_b"})

    def test_from_dict_rejects_an_unknown_relationship_value(self) -> None:
        with pytest.raises(EdgeValidationError, match="not one of"):
            CausalEdge.from_dict(
                {"from_event_id": "evt_a", "to_event_id": "evt_b", "relationship": "TELEPORTED"}
            )


class TestEdgeStoreIsMutationFree:
    def test_the_store_exposes_no_mutation_api(self) -> None:
        # Mirrors relay/test_relay.py's equivalent test for ChainStore:
        # the surest way to guarantee edges are never rewritten is to give
        # the class no method that could do it.
        forbidden = {"update", "delete", "remove", "replace", "modify", "edit", "clear", "pop"}
        present = {name for name in dir(EdgeStore) if not name.startswith("_")}
        assert not (present & forbidden)

    def test_append_then_edges_returns_them_in_order(self) -> None:
        store = EdgeStore()
        first = CausalEdge(
            from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.CAUSED
        )
        second = CausalEdge(
            from_event_id="evt_c", to_event_id="evt_b", relationship=RelationshipType.REQUIRED
        )
        store.append(first)
        store.append(second)
        assert store.edges() == [first, second]
        assert len(store) == 2

    def test_edges_returns_a_snapshot_not_a_live_view(self) -> None:
        store = EdgeStore()
        store.append(
            CausalEdge(
                from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.CAUSED
            )
        )
        snapshot = store.edges()
        store.append(
            CausalEdge(
                from_event_id="evt_c", to_event_id="evt_d", relationship=RelationshipType.CAUSED
            )
        )
        assert len(snapshot) == 1


class TestEdgeStorePersistence:
    def test_a_path_backed_store_writes_one_json_line_per_edge(self, tmp_path: Path) -> None:
        path = tmp_path / "edges.jsonl"
        edge = CausalEdge(
            from_event_id="evt_write_0007",
            to_event_id="evt_decision_0003",
            relationship=RelationshipType.CAUSED,
        )
        with EdgeStore(path) as store:
            store.append(edge)

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == edge.to_dict()

    def test_reopening_a_nonempty_edge_log_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "edges.jsonl"
        with EdgeStore(path) as store:
            store.append(
                CausalEdge(
                    from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.CAUSED
                )
            )

        with pytest.raises(EdgeStoreError, match="append-only"):
            EdgeStore(path)

    def test_load_edges_reads_back_what_was_appended(self, tmp_path: Path) -> None:
        path = tmp_path / "edges.jsonl"
        edges = [
            CausalEdge(
                from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.CAUSED
            ),
            CausalEdge(
                from_event_id="evt_c", to_event_id="evt_b", relationship=RelationshipType.REQUIRED
            ),
        ]
        with EdgeStore(path) as store:
            for edge in edges:
                store.append(edge)

        records = load_edges(path)
        rebuilt = [CausalEdge.from_dict(record) for record in records]
        assert rebuilt == edges

    def test_load_edges_marks_an_unparseable_line_rather_than_raising(self, tmp_path: Path) -> None:
        path = tmp_path / "edges.jsonl"
        good = CausalEdge(
            from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.CAUSED
        )
        path.write_text(json.dumps(good.to_dict()) + "\nnot json at all\n", encoding="utf-8")

        records = load_edges(path)
        assert records == [good.to_dict(), {"__unparseable__": "not json at all"}]

    def test_export_writes_every_edge_to_a_destination_file(self, tmp_path: Path) -> None:
        store = EdgeStore()
        edge = CausalEdge(
            from_event_id="evt_a", to_event_id="evt_b", relationship=RelationshipType.SUPERSEDED
        )
        store.append(edge)

        destination = tmp_path / "exported" / "edges.jsonl"
        store.export(destination)

        records = load_edges(destination)
        assert [CausalEdge.from_dict(r) for r in records] == [edge]


class TestEdgeIndex:
    def _index(self) -> EdgeIndex:
        return EdgeIndex(
            [
                # evt_write depends on (was caused by) evt_decision.
                CausalEdge(
                    from_event_id="evt_write",
                    to_event_id="evt_decision",
                    relationship=RelationshipType.CAUSED,
                ),
                # evt_write also required a prior claim.
                CausalEdge(
                    from_event_id="evt_write",
                    to_event_id="evt_claim",
                    relationship=RelationshipType.REQUIRED,
                ),
                # A second write superseded the first.
                CausalEdge(
                    from_event_id="evt_write_2",
                    to_event_id="evt_write",
                    relationship=RelationshipType.SUPERSEDED,
                ),
            ]
        )

    def test_edges_from_returns_every_edge_naming_that_event_as_the_effect(self) -> None:
        index = self._index()
        matches = index.edges_from("evt_write")
        assert {e.to_event_id for e in matches} == {"evt_decision", "evt_claim"}

    def test_edges_from_can_be_filtered_by_relationship(self) -> None:
        index = self._index()
        matches = index.edges_from("evt_write", relationship=RelationshipType.REQUIRED)
        assert [e.to_event_id for e in matches] == ["evt_claim"]

    def test_edges_to_returns_every_edge_naming_that_event_as_a_cause(self) -> None:
        index = self._index()
        matches = index.edges_to("evt_write")
        assert [e.from_event_id for e in matches] == ["evt_write_2"]

    def test_causes_of_is_the_one_hop_answer_to_which_decision_caused_this_write(self) -> None:
        index = self._index()
        assert set(index.causes_of("evt_write")) == {"evt_decision", "evt_claim"}

    def test_effects_of_is_the_inverse_of_causes_of(self) -> None:
        index = self._index()
        assert index.effects_of("evt_write") == ["evt_write_2"]

    def test_an_event_id_the_index_has_never_seen_returns_no_edges(self) -> None:
        # The index must not require its referenced ids to exist anywhere
        # else — cross-checking against a chain is a caller's job.
        index = self._index()
        assert index.causes_of("evt_never_recorded") == []

    def test_querying_an_absent_event_id_does_not_grow_the_index(self) -> None:
        # The lookup tables are plain dicts precisely so a miss cannot
        # insert an empty bucket. Under a defaultdict this assertion fails
        # after the first query, and the index would grow without bound in
        # any caller that probes ids it has not recorded.
        index = self._index()
        before = len(index._by_from) + len(index._by_to)
        index.causes_of("evt_never_recorded")
        index.effects_of("evt_also_never_recorded")
        assert len(index._by_from) + len(index._by_to) == before

    def test_the_direction_convention_is_from_effect_to_cause(self) -> None:
        # The single most confusable thing in this API. An edge points from
        # the effect back to its cause, matching how Event.parent_id already
        # points from a later event to the predecessor it reacted to. Stated
        # here as an executable definition so a future reader does not have
        # to infer it from the field names.
        decision = "evt_decision"
        write = "evt_write"
        index = self._index()

        # The write was caused by the decision, so the write is the effect.
        assert decision in index.causes_of(write)
        assert write in index.effects_of(decision)
        assert index.causes_of(decision) == []

    def test_all_returns_every_edge_the_index_was_built_from(self) -> None:
        index = self._index()
        assert len(index.all()) == 3
        assert len(index) == 3
