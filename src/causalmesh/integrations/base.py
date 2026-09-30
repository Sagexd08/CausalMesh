from __future__ import annotations

import inspect
from typing import Any, NamedTuple

from causalmesh.gateway.result import GatewayResult
from causalmesh.sdk.errors import MissingResourceError, ToolNotFoundError
from causalmesh.sdk.mesh import CausalMesh

# What a model can get wrong by itself: naming a tool that is not registered, or
# leaving out (or mangling) the argument the gate needs to decide on. These become
# an observation the model can read and correct. ``UnknownAgentError`` is not
# here on purpose: the agent id is configuration, so a misspelled one must raise
# rather than hide inside a tool message that leaves every call failing.
MODEL_ERRORS = (ToolNotFoundError, MissingResourceError)


class Observation(NamedTuple):
    """What a framework adapter hands back to a model after one tool call.

    ``is_error`` is True for anything the model did not get an answer to: a
    denial, a handler failure, or a call the adapter could not even attempt.
    """

    text: str
    is_error: bool


class BaseFrameworkAdapter:
    """Common abstraction for CausalMesh framework adapters.

    Provides standard routing to CausalMesh's execution boundary and
    utilities for safely formatting results into LLM-friendly text.
    """

    def __init__(self, mesh: CausalMesh, *, agent_id: str | None = None) -> None:
        """
        Args:
            mesh: A configured CausalMesh instance.
            agent_id: Default agent id. Falls back to the mesh's default when omitted.
        """
        self._mesh = mesh
        self._agent_id = agent_id

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> GatewayResult:
        """Route a synchronous tool call through the attached CausalMesh session."""
        return self._mesh.execute(
            agent_id=agent_id or self._agent_id,
            tool=tool_name,
            arguments=arguments,
        )

    async def acall_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> GatewayResult:
        """Route an asynchronous tool call through the attached CausalMesh session."""
        return await self._mesh.execute_async(
            agent_id=agent_id or self._agent_id,
            tool=tool_name,
            arguments=arguments,
        )

    def observe(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> Observation:
        """Run one model-requested call through the gate and phrase the outcome.

        The only place adapters turn a call into text, so a mistake by the model
        (``MODEL_ERRORS``) is an ``Action failed:`` answer everywhere, and an
        unknown agent (or any other error) raises everywhere.
        """
        try:
            result = self.call_tool(tool_name, arguments, agent_id=agent_id)
        except MODEL_ERRORS as exc:
            return Observation(f"Action failed: {exc}", True)
        return Observation(self.format_result(result), result.denied or result.failed)

    async def aobserve(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> Observation:
        """Async twin of ``observe``; it goes through ``acall_tool``."""
        try:
            result = await self.acall_tool(tool_name, arguments, agent_id=agent_id)
        except MODEL_ERRORS as exc:
            return Observation(f"Action failed: {exc}", True)
        return Observation(self.format_result(result), result.denied or result.failed)

    @staticmethod
    def bind_arguments(
        signature: inspect.Signature, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> dict[str, Any] | str:
        """The keyword arguments a handler takes, or an ``Action failed:`` message.

        Defaults are applied, so the gate sees what the handler will get.
        ``**kwargs`` is flattened rather than nested under its own name.
        """
        try:
            bound = signature.bind(*args, **kwargs)
        except TypeError as exc:
            return f"Action failed: Invalid arguments - {exc}"
        bound.apply_defaults()
        arguments: dict[str, Any] = {}
        for name, value in bound.arguments.items():
            kind = signature.parameters[name].kind
            if kind is inspect.Parameter.VAR_KEYWORD:
                arguments.update(value)
            elif kind is inspect.Parameter.VAR_POSITIONAL:
                if value:
                    return (
                        "Action failed: Invalid arguments - the gateway calls a handler "
                        "by keyword, so extra positional arguments cannot be passed"
                    )
            else:
                arguments[name] = value
        return arguments

    @staticmethod
    def format_result(result: GatewayResult) -> str:
        """Safely format a GatewayResult for an LLM observation string.

        Preserves policy denials and failures while avoiding leaking internal stack traces.
        """
        if result.denied:
            return f"Action denied by policy: {result.reason}"
        if result.failed:
            return f"Action failed: {result.reason}"

        # If the call was allowed but would have been refused under strict enforcement (e.g. C0-C2 arms)
        if result.would_refuse:
            return f"Action allowed (WARNING - would refuse under strict policy: {result.reason}). Result: {result.value}"

        return str(result.value)
