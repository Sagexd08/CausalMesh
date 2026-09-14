"""Provenance: what produced a result, and proof the evidence is unchanged.

Two artefacts, answering two questions:

- `Environment` — which code, on what machine, run by whom (§30, §32).
  Nothing here enters the signed chain: the chain is bit-reproducible, and
  a hostname or timestamp inside it would break that.
- `Manifest` — SHA-256 over every artifact a collection produced (§31).
  Tracked in git while `data/raw/` is not, so a published figure stays
  traceable to its run after the raw directory is gone.

A manifest proves integrity. The signed chain inside each artifact proves
authenticity. Neither substitutes for the other.
"""

from __future__ import annotations

from .environment import Environment, GitState, freeze_hash
from .manifest import (
    MANIFEST_VERSION,
    ArtifactEntry,
    CheckResult,
    Manifest,
    ManifestError,
    build,
    check,
    hash_file,
)

__all__ = [
    "MANIFEST_VERSION",
    "ArtifactEntry",
    "CheckResult",
    "Environment",
    "GitState",
    "Manifest",
    "ManifestError",
    "build",
    "check",
    "freeze_hash",
    "hash_file",
]
