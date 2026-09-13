"""Operational storage: the run index (spec §42, §63).

Operational, not evidential. The evidence is the signed chain and the run
artifacts under `data/raw/`; this index records which runs exist and what
state they reached, so a collection can be resumed and a duplicate
execution refused. Nothing here feeds a reported number.
"""

from __future__ import annotations

from .index import RunIndex, RunRecord

__all__ = ["RunIndex", "RunRecord"]
