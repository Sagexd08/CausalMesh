"""Framework-neutral integration interface for CausalMesh.

``GenericAdapter`` (no framework dependency), ``OpenAIAdapter`` (function
calling, no vendor SDK) and ``LangChainAdapter`` (requires
``langchain-core``, isolated behind an import guard) are implemented.
Anthropic ``tool_use``, LangGraph and CrewAI adapters are not; see
``docs/backlog.md``.

The key abstraction is ``AgentAdapter``: a protocol that any framework can
implement to route its tool calls through a ``CausalMesh`` session. Every
adapter here routes exclusively through ``BaseFrameworkAdapter.call_tool`` /
``acall_tool`` — i.e. through ``CausalMesh.execute`` / ``execute_async`` —
so there is one authorization path regardless of which framework is calling.

Example::

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

from .base import BaseFrameworkAdapter
from .generic import AgentAdapter, GenericAdapter
from .langchain import LangChainAdapter
from .openai import OpenAIAdapter
from .schema import tool_to_json_schema

__all__ = [
    "AgentAdapter",
    "BaseFrameworkAdapter",
    "GenericAdapter",
    "LangChainAdapter",
    "OpenAIAdapter",
    "tool_to_json_schema",
]
