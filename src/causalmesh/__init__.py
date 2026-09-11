"""CausalMesh — separating information from enforcement in distributed LLM coding agents.

The package is layered so that dependencies run one way only (spec §5):

    runtime  ->  relay  ->  raw evidence  ->  verifier  ->  analysis

Analysis never mutates runtime state, and the verifier never depends on the
relay being online. Those boundaries are enforced by tests, not convention.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
