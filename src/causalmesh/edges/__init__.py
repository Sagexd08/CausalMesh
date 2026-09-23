"""Causal edges over the chain (`docs/backlog.md`, "Causal edges over the chain").

The chain proves *sequence*: event N's hash depends on event N-1's. It does
not record *relationships* between events, so "which decision caused this
write" requires reading the chain in order and matching timestamps by eye.
This package is a typed relationship layer over the existing chain — a store
for `(from_event_id, to_event_id, relationship)` triples and a query surface
over them.

It is additive. Nothing here changes what is signed or how the chain is
verified: an edge is never hashed into `crypto.chain`'s digest and carries no
signature. `tasks/runner.py` populates one relationship today — a denied
write's `FAILURE` event back to the `POLICY_VERDICT` that refused it — and
callers record further edges explicitly, the same way `Event.references` is
plumbed through but left for a caller to use.
"""

from __future__ import annotations

from .query import EdgeIndex
from .report import EdgeReportError, RunEdges, collect_edges, edges_for_run, run_edges_to_dict
from .store import EdgeStore, EdgeStoreError, load_edges
from .types import CausalEdge, EdgeValidationError, RelationshipType

__all__ = [
    "CausalEdge",
    "EdgeIndex",
    "EdgeReportError",
    "EdgeStore",
    "EdgeStoreError",
    "EdgeValidationError",
    "RelationshipType",
    "RunEdges",
    "collect_edges",
    "edges_for_run",
    "load_edges",
    "run_edges_to_dict",
]
