"""LangChain integration for CausalMesh.

Provides an adapter that exposes registered CausalMesh tools as LangChain tools.
Requires `langchain-core` to be installed.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from causalmesh.gateway.tool import Tool
    from causalmesh.sdk.mesh import CausalMesh

try:
    from langchain_core.tools import BaseTool, StructuredTool
except ImportError:
    BaseTool = None  # type: ignore[misc,assignment]
    StructuredTool = None  # type: ignore[misc,assignment]


class LangChainAdapter:
    """Wraps a CausalMesh instance to expose its tools to LangChain agents.

    Requires ``langchain-core``.
    """

    def __init__(self, mesh: CausalMesh, *, agent_id: str | None = None) -> None:
        """
        Args:
            mesh:     A configured ``CausalMesh`` instance.
            agent_id: Default agent id for tools exposed by this adapter.
        """
        if StructuredTool is None:
            raise ImportError(
                "langchain-core is required for the LangChain integration. "
                "Install it with: pip install langchain-core"
            )
        self._mesh = mesh
        self._agent_id = agent_id

    def get_tools(self, *, agent_id: str | None = None) -> list[BaseTool]:
        """Return all registered CausalMesh tools as LangChain StructuredTools."""
        aid = agent_id or self._agent_id
        langchain_tools: list[BaseTool] = []
        for name in self._mesh.registered_tools():
            tool = self._mesh._gateway.get_tool(name)
            langchain_tools.append(self._create_tool(tool, aid))
        return langchain_tools

    def _create_tool(self, tool: Tool, agent_id: str | None) -> BaseTool:
        """Build a LangChain StructuredTool that routes through CausalMesh."""
        original_sig = inspect.signature(tool.handler)

        def _dynamic_handler(*args: Any, **kwargs: Any) -> Any:
            # Bind arguments according to the original signature to extract kwargs properly
            bound = original_sig.bind(*args, **kwargs)
            bound.apply_defaults()

            result = self._mesh.execute(
                agent_id=agent_id,
                tool=tool.name,
                arguments=bound.arguments,
            )

            # Surface authorization denials clearly to the agent model
            if result.denied:
                return f"Action denied by policy: {result.reason}"
            if result.failed:
                return f"Action failed: {result.reason}"
            return result.value

        # Trick LangChain into reading the original signature and docstring
        _dynamic_handler.__signature__ = original_sig  # type: ignore[attr-defined]
        _dynamic_handler.__name__ = tool.name
        _dynamic_handler.__doc__ = tool.description or f"Executes the {tool.name} action."
        _dynamic_handler.__annotations__ = getattr(tool.handler, "__annotations__", {})

        return StructuredTool.from_function(
            func=_dynamic_handler,
            name=tool.name,
            description=_dynamic_handler.__doc__,
        )
