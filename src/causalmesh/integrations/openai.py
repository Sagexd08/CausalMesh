import json
from typing import Any

from .base import BaseFrameworkAdapter
from .schema import tool_to_json_schema


class OpenAIAdapter(BaseFrameworkAdapter):
    """Adapter for executing OpenAI function-calling tool calls through CausalMesh.

    Translates registered CausalMesh tools into OpenAI `{"type": "function"}` definitions,
    and executes OpenAI `tool_call` payloads securely through the CausalMesh gateway.
    """

    def get_tools(self, *, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Return all registered CausalMesh tools formatted as OpenAI tools."""
        tools = []
        for name in sorted(self._mesh.registered_tools()):
            tool = self._mesh.get_tool(name)
            desc = tool.description or f"Executes the {name} action."
            schema = tool_to_json_schema(name, desc, tool.handler)
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": desc,
                        "parameters": schema,
                    },
                }
            )
        return tools

    def handle_tool_call(
        self, tool_call: dict[str, Any], *, agent_id: str | None = None
    ) -> dict[str, Any]:
        """Execute a single OpenAI tool_call securely through CausalMesh.

        Args:
            tool_call: An OpenAI tool_call dict.
            agent_id: Optional agent identity.

        Returns:
            An OpenAI chat message dict with `role="tool"`.
        """
        call_id = tool_call.get("id", "")

        if tool_call.get("type") != "function":
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "Action failed: Unsupported tool_call type, expected 'function'.",
            }

        function_data = tool_call.get("function", {})
        tool_name = function_data.get("name", "")
        arguments_str = function_data.get("arguments", "{}")

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError as exc:
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "content": f"Action failed: Malformed JSON arguments - {exc}",
            }

        result = self.call_tool(tool_name, arguments, agent_id=agent_id)

        return {"role": "tool", "tool_call_id": call_id, "content": self.format_result(result)}

    async def ahandle_tool_call(
        self, tool_call: dict[str, Any], *, agent_id: str | None = None
    ) -> dict[str, Any]:
        """Asynchronously execute a single OpenAI tool_call securely through CausalMesh."""
        call_id = tool_call.get("id", "")

        if tool_call.get("type") != "function":
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "content": "Action failed: Unsupported tool_call type, expected 'function'.",
            }

        function_data = tool_call.get("function", {})
        tool_name = function_data.get("name", "")
        arguments_str = function_data.get("arguments", "{}")

        try:
            arguments = json.loads(arguments_str)
        except json.JSONDecodeError as exc:
            return {
                "role": "tool",
                "tool_call_id": call_id,
                "content": f"Action failed: Malformed JSON arguments - {exc}",
            }

        result = await self.acall_tool(tool_name, arguments, agent_id=agent_id)

        return {"role": "tool", "tool_call_id": call_id, "content": self.format_result(result)}

    def handle_tool_calls(
        self, tool_calls: list[dict[str, Any]], *, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Deterministically process multiple tool calls sequentially."""
        return [self.handle_tool_call(call, agent_id=agent_id) for call in tool_calls]

    async def ahandle_tool_calls(
        self, tool_calls: list[dict[str, Any]], *, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Deterministically process multiple tool calls sequentially in an async context."""
        results = []
        for call in tool_calls:
            results.append(await self.ahandle_tool_call(call, agent_id=agent_id))
        return results
