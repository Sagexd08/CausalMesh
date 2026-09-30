"""Framework-neutral integration protocol and generic adapter.

``AgentAdapter`` is a ``Protocol`` that any framework-specific adapter
must satisfy.  It defines the minimal surface through which a framework
hands tool calls to CausalMesh.

``GenericAdapter`` is a concrete implementation for the common case where
no framework integration is needed — the developer's agent simply calls
``adapter.call_tool(...)`` directly.

The framework adapters (OpenAI, Anthropic, LangChain, LangGraph, CrewAI) live
in sibling modules.  Still not implemented:

- Human-in-the-loop approval from the SDK

These are tracked in docs/backlog.md per the project convention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from causalmesh.gateway.result import GatewayResult

from .base import BaseFrameworkAdapter

if TYPE_CHECKING:
    pass

__all__ = ["AgentAdapter", "GenericAdapter"]


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol that framework-specific adapters must implement.

    An adapter translates framework-native tool invocations into
    ``CausalMesh`` executions.  The returned ``GatewayResult`` carries
    the policy decision and the audit event identifier so the framework
    can surface denials to the agent.
    """

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> GatewayResult:
        """Route one tool call through CausalMesh.

        Args:
            tool_name: Name of the registered tool to call.
            arguments: Keyword arguments for the tool handler.
            agent_id:  Overrides the session-level default agent id.

        Returns:
            ``GatewayResult`` — the policy verdict and, when allowed, the
            handler's return value.
        """
        ...

    async def acall_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> GatewayResult:
        """Route one asynchronous tool call through CausalMesh."""
        ...


class GenericAdapter(BaseFrameworkAdapter):
    """A framework-neutral adapter for a ``CausalMesh`` session.

    Use this when there is no framework integration needed — the
    developer's agent calls ``adapter.call_tool(...)`` directly.

    Example::

        from causalmesh import CausalMesh, Tool
        from causalmesh.integrations import GenericAdapter

        mesh = CausalMesh.from_config("causalmesh.yaml")
        mesh.register_tool(Tool(name="read", handler=read_fn))

        adapter = GenericAdapter(mesh, agent_id="my-agent")
        result = adapter.call_tool("read", {"path": "README.md"})

        if result.denied:
            print(result.describe())
    """

    def __repr__(self) -> str:
        return f"<GenericAdapter agent_id={self._agent_id!r}>"
