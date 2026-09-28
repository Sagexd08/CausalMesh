#!/usr/bin/env python
"""Phase 1 basic agent example.

Shows the complete Phase 1 developer experience:

    1. Load CausalMesh from causalmesh.yaml
    2. Register read_file
    3. Register write_file
    4. Execute an allowed action (src/ is owned by coding-agent)
    5. Execute a denied action (production/ is owned by dba-agent)
    6. Print the human-readable result

Run from the examples/ directory:

    cd examples/
    python phase1_basic_agent.py

Or from the project root:

    python examples/phase1_basic_agent.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from the project root without `pip install -e .`
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from causalmesh import CausalMesh, Tool

# --------------------------------------------------------------------------- #
# Define simple tool handlers                                                   #
# These simulate what your real agent tools would do.                          #
# --------------------------------------------------------------------------- #

_FILESYSTEM: dict[str, str] = {
    "src/example.py": "# placeholder\n",
}


def read_file(path: str) -> str:
    """Read a file from the in-memory filesystem."""
    content = _FILESYSTEM.get(path)
    if content is None:
        raise FileNotFoundError(f"{path!r} not found in example filesystem")
    return content


def write_file(path: str, content: str) -> int:
    """Write a file to the in-memory filesystem."""
    _FILESYSTEM[path] = content
    return len(content.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Load CausalMesh                                                               #
# --------------------------------------------------------------------------- #

# Look for causalmesh.yaml next to this script, then upward.
config_path = Path(__file__).parent / "causalmesh.yaml"
if not config_path.is_file():
    print(f"No causalmesh.yaml found at {config_path}", file=sys.stderr)
    sys.exit(1)

mesh = CausalMesh.from_config(config_path)
print(f"CausalMesh loaded: arm={mesh.contract.arm}, run_id={mesh.run_id}")

# --------------------------------------------------------------------------- #
# Register tools                                                                #
# --------------------------------------------------------------------------- #

mesh.register_tool(
    Tool(
        name="read_file",
        handler=read_file,
        kind="filesystem",
        mutating=False,
        resource_args=["path"],
        description="Read a file from the filesystem.",
    )
)

mesh.register_tool(
    Tool(
        name="write_file",
        handler=write_file,
        kind="filesystem",
        mutating=True,
        resource_args=["path"],
        description="Write content to a file.",
    )
)

print(f"Registered tools: {mesh.registered_tools()}")

# --------------------------------------------------------------------------- #
# Step 4: Execute an ALLOWED action                                            #
# coding-agent owns src/, so writing there is permitted.                       #
# --------------------------------------------------------------------------- #

print("\n--- ALLOWED ACTION ---")
result = mesh.execute(
    agent_id="coding-agent",
    tool="write_file",
    arguments={
        "path": "src/example.py",
        "content": "print('hello from CausalMesh!')\n",
    },
)

print(f"allowed:  {result.allowed}")
print(f"executed: {result.executed}")
print(f"value:    {result.value}")
print(f"event_id: {result.event_id}")
print(result.describe())

# --------------------------------------------------------------------------- #
# Step 5: Execute a DENIED action                                              #
# production/ is owned by dba-agent; coding-agent is refused.                  #
# The handler is NEVER called for denied actions.                              #
# --------------------------------------------------------------------------- #

print("\n--- DENIED ACTION ---")
handler_sentinel: list[bool] = []

mesh.register_tool(
    Tool(
        name="write_protected_file",
        handler=lambda path, content: handler_sentinel.append(True),
        kind="filesystem",
        mutating=True,
    )
)

result2 = mesh.execute(
    agent_id="coding-agent",
    tool="write_protected_file",
    arguments={
        "path": "production/database.sql",
        "content": "DROP TABLE users;",
    },
)

print(f"denied:   {result2.denied}")
print(f"allowed:  {result2.allowed}")
print(f"handler called: {bool(handler_sentinel)}  (should be False)")
print(f"event_id: {result2.event_id}")

# --------------------------------------------------------------------------- #
# Step 6: Print the human-readable denial                                       #
# --------------------------------------------------------------------------- #

print()
print(result2.describe())

# --------------------------------------------------------------------------- #
# Boundary summary                                                              #
# --------------------------------------------------------------------------- #

summary = mesh.boundary_summary()
print(f"\nBoundary summary: {summary}")
print(f"Audit events recorded: {len(mesh.audit_events())}")
