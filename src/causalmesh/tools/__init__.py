"""The controlled tool API (spec §12).

Twelve operations, no unrestricted host shell. Every call resolves its paths
through the agent's workspace and reaches a tool only via the lifecycle
boundary.
"""

from __future__ import annotations

from .api import ALLOWED_COMMANDS, TOOL_NAMES, CommandResult, Toolbox, ToolError
from .executor import ToolExecutor

__all__ = [
    "ALLOWED_COMMANDS",
    "TOOL_NAMES",
    "CommandResult",
    "ToolError",
    "ToolExecutor",
    "Toolbox",
]
