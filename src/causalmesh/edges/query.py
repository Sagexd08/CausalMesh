"""A read-only query surface over a set of `CausalEdge`s.

`docs/backlog.md` frames the whole point of this layer as turning "which
decision caused this write" from a manual scan into a query. This module is
that query surface: it takes edges already loaded (from an `EdgeStore` or
from `load_edges`) and answers questions about them. It does not read files
itself and does not know about `EdgeStore`, so it works equally over edges
collected in a test, in memory during a run, or loaded from disk.

Nothing here requires the referenced event ids to exist in any chain. An
edge naming an event id this process has never seen is not an error at this
layer — cross-checking edges against a chain's actual events, if ever
needed, belongs to a caller that has both in hand, not to the query surface
itself.
"""

from __future__ import annotations

from .types import CausalEdge, RelationshipType

__all__ = ["EdgeIndex"]


class EdgeIndex:
    """An in-memory index over a fixed collection of edges.

    Built once from a snapshot; does not observe further appends to the
    `EdgeStore` it may have been built from. Callers that need a live view
    rebuild the index after new edges arrive, the same way `Relay.records()`
    returns a snapshot rather than a live handle.
    """

    def __init__(self, edges: list[CausalEdge]) -> None:
        self._edges = list(edges)
        # Plain dicts, not defaultdicts: every read below goes through
        # `.get(..., [])`, and a defaultdict would let a future `[...]` read
        # silently insert an empty list on every miss, growing the index as
        # a side effect of querying it.
        self._by_from: dict[str, list[CausalEdge]] = {}
        self._by_to: dict[str, list[CausalEdge]] = {}
        for edge in self._edges:
            self._by_from.setdefault(edge.from_event_id, []).append(edge)
            self._by_to.setdefault(edge.to_event_id, []).append(edge)

    def __len__(self) -> int:
        return len(self._edges)

    def all(self) -> list[CausalEdge]:
        return list(self._edges)

    def edges_from(
        self, event_id: str, *, relationship: RelationshipType | None = None
    ) -> list[CausalEdge]:
        """Edges where `event_id` is the effect, naming what it points back to as cause."""
        matches = self._by_from.get(event_id, [])
        if relationship is None:
            return list(matches)
        return [e for e in matches if e.relationship == relationship]

    def edges_to(
        self, event_id: str, *, relationship: RelationshipType | None = None
    ) -> list[CausalEdge]:
        """Edges where `event_id` is the cause, naming what pointed back to it as effect."""
        matches = self._by_to.get(event_id, [])
        if relationship is None:
            return list(matches)
        return [e for e in matches if e.relationship == relationship]

    def causes_of(self, event_id: str) -> list[str]:
        """Event ids directly named as a cause of `event_id`.

        This is one hop, not a transitive walk: "which decision caused this
        write" for the immediate decision. Callers wanting the full ancestry
        chain compose this themselves via repeated calls, which keeps this
        method's behaviour obvious for a graph that a caller may have
        constructed with cycles an automatic walk would need to guard
        against.
        """
        return [edge.to_event_id for edge in self.edges_from(event_id)]

    def effects_of(self, event_id: str) -> list[str]:
        """Event ids that directly name `event_id` as their cause."""
        return [edge.from_event_id for edge in self.edges_to(event_id)]
