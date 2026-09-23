"""Append-only storage for the signed chain (spec §31, §55).

Raw evidence is written once and never rewritten. The store therefore offers
`append` and readers, and no update or delete of any kind — §31 forbids
analysis from modifying `data/raw/`, and the cheapest way to guarantee that
is to give the code no way to express it.

JSONL is the on-disk format: one record per line, appended, flushed. A
crash mid-run leaves a truncated final line rather than a corrupted file,
and every complete line before it stays verifiable. A single JSON array
would have to be rewritten on every append and would be unreadable if the
process died before closing the bracket.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from ..crypto.chain import ChainedEvent

__all__ = ["ChainStore", "StoreError"]


class StoreError(RuntimeError):
    """Raised when the store cannot honour the append-only guarantee."""


class ChainStore:
    """Append-only store for chained events.

    With a `path`, records are durably appended to a JSONL file and also kept
    in memory for fast reads. Without one, the store is memory-only, which is
    what unit tests and dry runs use.
    """

    def __init__(self, path: Path | str | None = None, *, fsync: bool = False) -> None:
        self._path = Path(path) if path is not None else None
        self._fsync = fsync
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._path.exists() and self._path.stat().st_size > 0:
                raise StoreError(
                    f"{self._path} already contains data; raw chains are append-only "
                    "and must not be reopened for a new run"
                )
            self._handle = self._path.open("a", encoding="utf-8", newline="\n")
        else:
            self._handle = None

    def append(self, chained: ChainedEvent) -> None:
        """Append one record. There is deliberately no way to modify one."""
        line = json.dumps(chained.to_dict(), sort_keys=True, ensure_ascii=False)
        with self._lock:
            self._records.append(chained.to_dict())
            if self._handle is not None:
                self._handle.write(line + "\n")
                self._handle.flush()
                if self._fsync:
                    os.fsync(self._handle.fileno())

    def records(self) -> list[dict[str, Any]]:
        """Every record, in append order.

        Returns copies: a caller mutating a returned dict must not be able to
        alter what the store believes it holds.
        """
        with self._lock:
            return [dict(record) for record in self._records]

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def export(self, destination: Path) -> Path:
        """Write the chain to a JSONL file for offline verification."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, destination.open("w", encoding="utf-8", newline="\n") as handle:
            for record in self._records:
                handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
        return destination

    def close(self) -> None:
        with self._lock:
            if self._handle is not None:
                self._handle.flush()
                if self._fsync:
                    os.fsync(self._handle.fileno())
                self._handle.close()
                self._handle = None

    def __enter__(self) -> ChainStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
