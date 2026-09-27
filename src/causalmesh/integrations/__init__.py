"""Framework-neutral integration interface for CausalMesh.

Phase 1 defines the protocol and a minimal generic adapter.  Framework-
specific integrations (OpenAI, Claude, LangGraph, CrewAI) are future work
and are *not* implemented here.

The key abstraction is ``AgentAdapter``: a protocol that any framework can
implement to route its tool calls through a ``CausalMesh`` session.

Example future usage (not yet implemented)::

    class MyFrameworkAdapter(AgentAdapter):
        def on_tool_call(self, call: FrameworkToolCall) -> FrameworkResult:
            result = self.mesh.execute(
                agent_id=call.agent_id,
                tool=call.tool_name,
                arguments=call.arguments,
            )
            return FrameworkResult.from_gateway(result)
"""

from __future__ import annotations

from .generic import AgentAdapter, GenericAdapter
from .langchain import LangChainAdapter

__all__ = ["AgentAdapter", "GenericAdapter", "LangChainAdapter"]
