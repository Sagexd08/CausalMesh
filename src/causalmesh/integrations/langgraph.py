"""LangGraph integration for CausalMesh.

LangGraph's prebuilt agents and ``ToolNode`` run ``langchain-core`` tools, so
this adapter reuses ``LangChainAdapter``'s tool construction outright: the tools
it hands to a graph are the same ``StructuredTool`` objects, and each one
routes through ``BaseFrameworkAdapter.observe`` and so through
``CausalMesh.execute`` / ``execute_async``. There is no second path.

What this class adds is the LangGraph-shaped entry point, ``tool_node()``, and
an import guard on ``langgraph`` itself. Importing ``causalmesh.integrations``
works without either package installed.

Not validated: no hosted model has driven a graph through this adapter. The
tests run a real ``ToolNode`` and a real prebuilt agent, when ``langgraph`` is
installed, against a scripted fake chat model.

``ToolNode`` re-raises a tool's exception unless ``handle_tool_errors`` says
otherwise. Leave it at its default: a catch-all handler (``True``, or a tuple
containing ``Exception``) would also swallow ``UnknownAgentError``, which is
meant to stop the run.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .langchain import LangChainAdapter

if TYPE_CHECKING:
    from causalmesh.sdk.mesh import CausalMesh

try:
    from langgraph.prebuilt import ToolNode
except ImportError:
    ToolNode = None  # type: ignore[misc,assignment]


class LangGraphAdapter(LangChainAdapter):
    """Exposes registered CausalMesh tools to LangGraph graphs and agents.

    Requires ``langgraph`` (which brings ``langchain-core``).

    Example::

        adapter = LangGraphAdapter(mesh, agent_id="my-agent")
        graph.add_node("tools", adapter.tool_node())
        # or, for a prebuilt agent:
        create_react_agent(model, adapter.get_tools())
    """

    def __init__(self, mesh: CausalMesh, *, agent_id: str | None = None) -> None:
        """
        Args:
            mesh:     A configured ``CausalMesh`` instance.
            agent_id: Default agent id for tools exposed by this adapter.
        """
        if ToolNode is None:
            raise ImportError(
                "langgraph is required for the LangGraph integration. "
                "Install it with: pip install langgraph"
            )
        super().__init__(mesh, agent_id=agent_id)

    def tool_node(self, *, agent_id: str | None = None, **kwargs: Any) -> Any:
        """A ``langgraph.prebuilt.ToolNode`` over every registered CausalMesh tool.

        ``kwargs`` are passed to ``ToolNode`` (``name``, ``messages_key``, ...).
        """
        return ToolNode(self.get_tools(agent_id=agent_id), **kwargs)

    def __repr__(self) -> str:
        return f"<LangGraphAdapter agent_id={self._agent_id!r}>"
