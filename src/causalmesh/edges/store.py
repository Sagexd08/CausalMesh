"""Append-only storage for causal edges.

Mirrors `relay.store.ChainStore`'s shape deliberately: edges are a sibling
artifact to the signed chain, not a rewrite of it. `ChainStore` offers
`append` and readers and no update or delete of any kind, because §31
forbids analysis from modifying raw evidence; edges are not signed evidence,
but the same append-only discipline keeps "why was this edge here" always
answerable from history rather than from a mutated present.

JSONL on disk for the same reason `store.py` gives: a crash mid-run leaves a
truncated final line rather than a corrupted file, and a single JSON array
would have to be rewritten on every append.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .types import CausalEdge

__all__ = ["EdgeStore", "EdgeStoreError", "load_edges"]


class EdgeStoreError(RuntimeError):
    """Raised when the store cannot honour the append-only guarantee."""


class EdgeStore:
    """Append-only store for `CausalEdge` records.

    With a `path`, edges are durably appended to a JSONL file (`edges.jsonl`
    by convention, as a sibling to `chain.jsonl`) and also kept in memory for
    fast reads. Without one, the store is memory-only, which is what unit
    tests use.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._edges: list[CausalEdge] = []

        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists() and self._path.stat().st_size > 0:
                raise EdgeStoreError(
                    f"{self._path} already contains data; edge logs are append-only "
                    "and must not be reopened for a new run"
                )
            self._handle = self._path.open("a", encoding="utf-8", newline="\n")
        else:
            self._handle = None

    def append(self, edge: CausalEdge) -> None:
        """Append one edge. There is deliberately no way to modify one."""
        line = json.dumps(edge.to_dict(), sort_keys=True, ensure_ascii=False)
        with self._lock:
            self._edges.append(edge)
            if self._handle is not None:
                self._handle.write(line + "\n")
                self._handle.flush()

    def edges(self) -> list[CausalEdge]:
        """Every edge, in append order."""
        with self._lock:
            return list(self._edges)

    def __len__(self) -> int:
        with self._lock:
            return len(self._edges)

    def export(self, destination: Path) -> Path:
        """Write every edge to a JSONL file."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, destination.open("w", encoding="utf-8", newline="\n") as handle:
            for edge in self._edges:
                handle.write(json.dumps(edge.to_dict(), sort_keys=True, ensure_ascii=False) + "\n")
        return destination

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()
                self._handle.close()
                self._handle = None

    def __enter__(self) -> EdgeStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


def load_edges(path: Path) -> list[dict[str, Any]]:
    """Read an edges JSONL file into raw records.

    Records are returned undecoded, matching `verifier.offline.load_chain`'s
    approach: a malformed line becomes a located problem for the caller to
    report rather than aborting the whole load.
    """
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                records.append({"__unparseable__": stripped[:200]})
    return records
