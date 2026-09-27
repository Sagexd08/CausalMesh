"""CausalMesh — separating information from enforcement in distributed LLM coding agents.

The package is layered so that dependencies run one way only (spec §5):

    runtime  ->  relay  ->  raw evidence  ->  verifier  ->  analysis

Analysis never mutates runtime state, and the verifier never depends on the
relay being online. Those boundaries are enforced by tests, not convention.

Phase 1 adds a developer-facing SDK.  The quickstart::

    from causalmesh import CausalMesh, Tool

    mesh = CausalMesh.from_config("causalmesh.yaml")
    mesh.register_tool(Tool(name="write_file", handler=fn, mutating=True))
    result = mesh.execute(agent_id="my-agent", tool="write_file", arguments={...})
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["CausalMesh", "Tool", "__version__"]

def __getattr__(name: str):
    if name == "CausalMesh":
        from causalmesh.sdk.mesh import CausalMesh
        return CausalMesh
    if name == "Tool":
        from causalmesh.gateway.tool import Tool
        return Tool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
