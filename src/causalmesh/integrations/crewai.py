"""CrewAI integration for CausalMesh.

Exposes registered CausalMesh tools as ``crewai.tools.BaseTool`` subclasses, so
they can be given to a CrewAI ``Agent(tools=[...])``. Requires ``crewai``
(which brings ``pydantic``), isolated behind an import guard so importing
``causalmesh.integrations`` works without it.

Every tool's ``_run`` / ``_arun`` goes through ``BaseFrameworkAdapter.observe`` /
``aobserve`` and so through ``CausalMesh.execute`` / ``execute_async``. The
handler is never called from here.

Not validated against the real package. ``crewai`` is heavy and was not
installed to develop this adapter, so the ``BaseTool`` contract used here
(a pydantic model with ``name``, ``description`` and ``args_schema`` fields, an
abstract ``_run(*args, **kwargs)`` and an optional ``_arun``) is written from the
public interface and exercised only against a minimal fake with those members.
``tests/integration/test_crewai_adapter.py`` has tests that run against the real
package when it is installed and are skipped, with a reason, when it is not.
"""

from __future__ import annotations

import inspect
import types
from typing import TYPE_CHECKING, Any, get_type_hints

from .base import BaseFrameworkAdapter

if TYPE_CHECKING:
    from causalmesh.gateway.tool import Tool
    from causalmesh.sdk.mesh import CausalMesh

try:
    from crewai.tools import BaseTool  # type: ignore[import-not-found,unused-ignore]
    from pydantic import BaseModel, ConfigDict, create_model
except ImportError:
    BaseTool = None  # type: ignore[misc,assignment]
    BaseModel = None  # type: ignore[misc,assignment]
    ConfigDict = None  # type: ignore[misc,assignment]
    create_model = None  # type: ignore[assignment]


class CrewAIAdapter(BaseFrameworkAdapter):
    """Wraps a CausalMesh instance to expose its tools to CrewAI agents.

    Requires ``crewai``.

    Example::

        adapter = CrewAIAdapter(mesh, agent_id="my-agent")
        Agent(role="...", goal="...", backstory="...", tools=adapter.get_tools())
    """

    def __init__(self, mesh: CausalMesh, *, agent_id: str | None = None) -> None:
        """
        Args:
            mesh:     A configured ``CausalMesh`` instance.
            agent_id: Default agent id for tools exposed by this adapter.
        """
        if BaseTool is None:
            raise ImportError(
                "crewai is required for the CrewAI integration. Install it with: pip install crewai"
            )
        super().__init__(mesh, agent_id=agent_id)

    def get_tools(self, *, agent_id: str | None = None) -> list[Any]:
        """Return all registered CausalMesh tools as CrewAI ``BaseTool`` instances."""
        aid = agent_id or self._agent_id
        return [
            self._create_tool(self._mesh.get_tool(name), aid)
            for name in sorted(self._mesh.registered_tools())
        ]

    def _create_tool(self, tool: Tool, agent_id: str | None) -> Any:
        """Build a ``BaseTool`` subclass instance that routes through CausalMesh."""
        signature = inspect.signature(tool.handler)
        name = tool.name
        adapter = self

        def _run(_self: Any, *args: Any, **kwargs: Any) -> str:
            arguments = adapter.bind_arguments(signature, args, kwargs)
            if isinstance(arguments, str):
                return arguments
            return adapter.observe(name, arguments, agent_id=agent_id).text

        async def _arun(_self: Any, *args: Any, **kwargs: Any) -> str:
            arguments = adapter.bind_arguments(signature, args, kwargs)
            if isinstance(arguments, str):
                return arguments
            return (await adapter.aobserve(name, arguments, agent_id=agent_id)).text

        namespace: dict[str, Any] = {
            "__annotations__": {"name": str, "description": str, "args_schema": type[BaseModel]},
            "__module__": __name__,
            "__doc__": tool.description,
            "name": name,
            "description": tool.description or f"Executes the {name} action.",
            "args_schema": _args_model(tool),
            "_run": _run,
            "_arun": _arun,
        }
        tool_class = types.new_class(
            f"CausalMesh_{name}", (BaseTool,), exec_body=lambda ns: ns.update(namespace)
        )
        return tool_class()

    def __repr__(self) -> str:
        return f"<CrewAIAdapter agent_id={self._agent_id!r}>"


def _args_model(tool: Tool) -> Any:
    """A pydantic model of the handler's parameters, for ``args_schema``."""
    signature = inspect.signature(tool.handler)
    try:
        hints = get_type_hints(tool.handler)
    except (TypeError, ValueError, NameError):
        hints = {}
    fields: dict[str, Any] = {}
    for param_name, param in signature.parameters.items():
        if param_name in ("self", "cls"):
            continue
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param_name] = (hints.get(param_name, Any), default)
    return create_model(
        f"{tool.name}_input",
        __config__=ConfigDict(arbitrary_types_allowed=True),
        **fields,
    )
