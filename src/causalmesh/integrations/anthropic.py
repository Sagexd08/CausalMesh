"""Anthropic Messages ``tool_use`` / ``tool_result`` integration for CausalMesh.

No vendor SDK is imported. The adapter speaks the content-block shapes of the
Messages API as plain dicts, so it works with the raw HTTP response body, and it
also accepts SDK block objects (anything exposing ``model_dump()`` or the
``type`` / ``id`` / ``name`` / ``input`` attributes).

Shapes, as documented for the Messages API:

- a tool definition is ``{"name", "description", "input_schema"}``;
- the model asks for a tool with a ``{"type": "tool_use", "id", "name",
  "input"}`` block in an assistant message;
- the caller answers with a ``user`` message whose content holds one
  ``{"type": "tool_result", "tool_use_id", "content", "is_error"}`` block per
  ``tool_use`` block.

Every call goes through ``BaseFrameworkAdapter.observe`` and so through
``CausalMesh.execute``; nothing here reaches a handler directly.

Not validated: no real Claude model has produced a ``tool_use`` block for this
adapter. The block shapes follow the public documentation and are checked only
against hand-written blocks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .base import BaseFrameworkAdapter, Observation
from .schema import tool_to_json_schema

_FIELDS = ("type", "id", "name", "input")


class AnthropicAdapter(BaseFrameworkAdapter):
    """Executes Anthropic ``tool_use`` blocks through CausalMesh.

    Example::

        adapter = AnthropicAdapter(mesh, agent_id="my-agent")
        response = post_messages(tools=adapter.get_tools(), messages=messages)
        reply = adapter.handle_message(response)   # a user message, or None
        if reply is not None:
            messages += [{"role": response["role"], "content": response["content"]}, reply]
    """

    def get_tools(self, *, agent_id: str | None = None) -> list[dict[str, Any]]:
        """Return all registered CausalMesh tools as Anthropic tool definitions.

        ``agent_id`` is accepted for symmetry with ``OpenAIAdapter`` and does
        not change the definitions: tools are not filtered per agent.
        """
        tools = []
        for name in sorted(self._mesh.registered_tools()):
            tool = self._mesh.get_tool(name)
            desc = tool.description or f"Executes the {name} action."
            tools.append(
                {
                    "name": name,
                    "description": desc,
                    "input_schema": tool_to_json_schema(name, desc, tool.handler),
                }
            )
        return tools

    # ------------------------------------------------------------------ #
    # One block                                                            #
    # ------------------------------------------------------------------ #

    def handle_tool_use(self, block: Any, *, agent_id: str | None = None) -> dict[str, Any]:
        """Execute one ``tool_use`` block and return its ``tool_result`` block.

        A denial, a handler failure and a bad call by the model all come back
        as a ``tool_result`` with ``is_error`` true, for the model to read. An
        unknown ``agent_id`` raises ``UnknownAgentError`` instead: it is
        configuration, not model output.
        """
        fields = _fields(block)
        parsed = self._parse_tool_use(fields)
        if isinstance(parsed, str):
            return self._tool_result(fields["id"], Observation(parsed, True))
        tool_name, arguments = parsed
        return self._tool_result(
            fields["id"], self.observe(tool_name, arguments, agent_id=agent_id)
        )

    async def ahandle_tool_use(self, block: Any, *, agent_id: str | None = None) -> dict[str, Any]:
        """Asynchronously execute one ``tool_use`` block (through ``acall_tool``)."""
        fields = _fields(block)
        parsed = self._parse_tool_use(fields)
        if isinstance(parsed, str):
            return self._tool_result(fields["id"], Observation(parsed, True))
        tool_name, arguments = parsed
        return self._tool_result(
            fields["id"], await self.aobserve(tool_name, arguments, agent_id=agent_id)
        )

    # ------------------------------------------------------------------ #
    # Several blocks, one message                                          #
    # ------------------------------------------------------------------ #

    def handle_tool_uses(
        self, blocks: list[Any], *, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Execute the ``tool_use`` blocks of a content list, in order.

        Blocks of any other type (``text``, ``thinking``, server-side tool
        blocks) are not this caller's to answer and are skipped.
        """
        return [
            self.handle_tool_use(block, agent_id=agent_id)
            for block in blocks
            if _fields(block)["type"] == "tool_use"
        ]

    async def ahandle_tool_uses(
        self, blocks: list[Any], *, agent_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Async twin of ``handle_tool_uses``; blocks run sequentially, in order."""
        return [
            await self.ahandle_tool_use(block, agent_id=agent_id)
            for block in blocks
            if _fields(block)["type"] == "tool_use"
        ]

    def handle_message(self, message: Any, *, agent_id: str | None = None) -> dict[str, Any] | None:
        """Answer an assistant message's ``tool_use`` blocks with one user message.

        Returns ``{"role": "user", "content": [tool_result, ...]}``, or ``None``
        when the message holds no ``tool_use`` block (the model's turn is over,
        and an empty user message would be rejected by the API).
        """
        results = self.handle_tool_uses(_content(message), agent_id=agent_id)
        return {"role": "user", "content": results} if results else None

    async def ahandle_message(
        self, message: Any, *, agent_id: str | None = None
    ) -> dict[str, Any] | None:
        """Async twin of ``handle_message``."""
        results = await self.ahandle_tool_uses(_content(message), agent_id=agent_id)
        return {"role": "user", "content": results} if results else None

    # ------------------------------------------------------------------ #
    # Internals                                                            #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tool_result(tool_use_id: str, observation: Observation) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": observation.text,
            "is_error": observation.is_error,
        }

    @staticmethod
    def _parse_tool_use(fields: dict[str, Any]) -> tuple[str, dict[str, Any]] | str:
        """The tool name and input of a ``tool_use`` block, or the message to return.

        Everything here is model output, so a bad value is an answer for the
        model to read and correct, not an exception for the caller's loop.
        """
        if fields["type"] != "tool_use":
            return "Action failed: Unsupported block type, expected 'tool_use'."
        name = fields["name"]
        if not isinstance(name, str) or not name:
            return "Action failed: tool_use block has no tool name."
        arguments = fields["input"]
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            return "Action failed: Tool input must be a JSON object."
        return name, arguments


def _fields(block: Any) -> dict[str, Any]:
    """``type``, ``id``, ``name`` and ``input`` of a block dict or SDK block object.

    ``id`` is always a string, since it goes straight into ``tool_use_id``.
    """
    if not isinstance(block, Mapping) and callable(getattr(block, "model_dump", None)):
        block = block.model_dump()
    if isinstance(block, Mapping):
        found = {key: block.get(key) for key in _FIELDS}
    else:
        found = {key: getattr(block, key, None) for key in _FIELDS}
    if not isinstance(found["id"], str):
        found["id"] = ""
    return found


def _content(message: Any) -> list[Any]:
    """The content blocks of an assistant message (dict or SDK object) or of a bare list."""
    if isinstance(message, list | tuple):
        return list(message)
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    # A string content is plain text: there is nothing to execute in it.
    return list(content) if isinstance(content, list | tuple) else []
