from typing import Any

from causalmesh.gateway.result import GatewayResult
from causalmesh.sdk.mesh import CausalMesh


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
