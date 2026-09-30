"""Framework-neutral integration interface for CausalMesh.

``GenericAdapter`` (no framework dependency), ``OpenAIAdapter`` (function
calling) and ``AnthropicAdapter`` (Messages ``tool_use`` / ``tool_result``
blocks), both without a vendor SDK, plus ``LangChainAdapter``,
``LangGraphAdapter`` and ``CrewAIAdapter`` (each needs its framework, isolated
behind an import guard) are implemented. None has been driven by a real hosted
model; ``docs/adapters.md`` says what each is tested against.

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

from .anthropic import AnthropicAdapter
from .base import BaseFrameworkAdapter, Observation
from .crewai import CrewAIAdapter
from .generic import AgentAdapter, GenericAdapter
from .langchain import LangChainAdapter
from .langgraph import LangGraphAdapter
from .openai import OpenAIAdapter
from .schema import tool_to_json_schema

__all__ = [
    "AgentAdapter",
    "AnthropicAdapter",
    "BaseFrameworkAdapter",
    "CrewAIAdapter",
    "GenericAdapter",
    "LangChainAdapter",
    "LangGraphAdapter",
    "Observation",
    "OpenAIAdapter",
    "tool_to_json_schema",
]
