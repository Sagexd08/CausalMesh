"""Terminal interfaces.

`monitor` is a read-only live view of a collection while it executes. It
opens the run index read-only and never writes, so attaching it to a run in
flight cannot interfere with the process doing the work.
"""

from __future__ import annotations

from .monitor import Snapshot, read_snapshot, render

__all__ = ["Snapshot", "read_snapshot", "render"]
