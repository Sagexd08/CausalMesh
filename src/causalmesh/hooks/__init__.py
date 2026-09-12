"""The lifecycle boundary and its gates (spec §13).

Every tool call passes through `LifecycleBoundary.invoke`. The gate is
supplied from outside, so an arm's enforcement behaviour is an installed
object rather than a branch inside the boundary.
"""

from __future__ import annotations

from .gates import AllowAllGate, ClaimGate, gate_for_arm
from .lifecycle import (
    MUTATING_TOOLS,
    TOOL_EVENT_TYPES,
    Gate,
    GateDecision,
    HookContext,
    LifecycleBoundary,
    ToolCall,
    ToolOutcome,
    ToolResult,
)

__all__ = [
    "MUTATING_TOOLS",
    "TOOL_EVENT_TYPES",
    "AllowAllGate",
    "ClaimGate",
    "Gate",
    "GateDecision",
    "HookContext",
    "LifecycleBoundary",
    "ToolCall",
    "ToolOutcome",
    "ToolResult",
    "gate_for_arm",
]
