"""The gateway package.

Exports the two types a developer needs directly::

    from causalmesh.gateway import Tool, ToolGateway
"""

from __future__ import annotations

from .gateway import ToolGateway
from .result import GatewayResult
from .tool import Tool

__all__ = ["GatewayResult", "Tool", "ToolGateway"]
