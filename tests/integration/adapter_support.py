"""Shared session and fakes for the framework-adapter tests.

One mesh, built the same way for every adapter, so a property such as "a denied
call never reaches the handler" is stated once and checked through each one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from causalmesh import CausalMesh, Tool
from causalmesh.policy.contract import Contract

CONTRACT_YAML = """
version: 1
roles:
  - agent_id: test-agent
    archetype: writer
    owns:
      - allowed/
  - agent_id: admin-agent
    archetype: admin
    owns:
      - forbidden/
policy:
  arm: {arm}
  contested:
    forbidden/: exclusive
evidence:
  sign: true
  verify_on_exit: false
"""


@dataclass
class Session:
    """A mesh plus the record of what its handlers actually ran and how often the gate ran."""

    mesh: CausalMesh
    called: list[str] = field(default_factory=list)
    gate_entries: list[str] = field(default_factory=list)


def build_session(tmp_path: Path, *, arm: str = "C3") -> Session:
    """Register a sync writer, an async writer, an optional-path writer and a read-only tool."""
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT_YAML.format(arm=arm))
    mesh = CausalMesh(
        agent_id="test-agent",
        contract=Contract.find(tmp_path),
        seed=b"test-seed-00000000000000000000000",
    )
    session = Session(mesh)

    def write_file(path: str, content: str = "") -> str:
        session.called.append(path)
        return f"written:{path}"

    async def async_write(path: str, content: str = "") -> str:
        session.called.append(path)
        return f"async-written:{path}"

    def write_optional(path: str | None = None) -> str:
        session.called.append(str(path))
        return f"optional:{path}"

    def explode(path: str) -> str:
        session.called.append(path)
        raise RuntimeError("handler exploded")

    def lookup(key: str, limit: int = 3) -> str:
        session.called.append(key)
        return f"found:{key}:{limit}"

    for name, handler, description in (
        ("write_file", write_file, "Write a file"),
        ("async_write", async_write, "Async write"),
        ("write_optional", write_optional, "Write to an optional path"),
        ("explode", explode, "A tool whose handler raises"),
    ):
        mesh.register_tool(
            Tool(
                name=name,
                handler=handler,
                kind="filesystem",
                mutating=True,
                description=description,
                resource_args=["path"],
            )
        )
    mesh.register_tool(
        Tool(
            name="lookup",
            handler=lookup,
            mutating=False,
            description="Read-only lookup",
        )
    )

    # Count every entry into the boundary. A call that skips the gate never
    # reaches it, so this is what makes "went through the authorization path"
    # an observable fact rather than an assumption.
    boundary = mesh._gateway._boundary
    real_invoke = boundary.invoke

    def counting_invoke(call: Any, executor: Any, **kwargs: Any) -> Any:
        session.gate_entries.append(call.tool)
        return real_invoke(call, executor, **kwargs)

    real_invoke_async = boundary.invoke_async

    async def counting_invoke_async(call: Any, executor: Any, **kwargs: Any) -> Any:
        session.gate_entries.append(call.tool)
        return await real_invoke_async(call, executor, **kwargs)

    boundary.invoke = counting_invoke  # type: ignore[method-assign]
    boundary.invoke_async = counting_invoke_async  # type: ignore[method-assign]
    return session


# --- a faithful minimal stand-in for crewai.tools.BaseTool ------------------


def make_fake_crewai_base() -> type:
    """The parts of ``crewai.tools.BaseTool`` the adapter relies on, and nothing else.

    A pydantic model with ``name``, ``description`` and ``args_schema`` fields,
    an abstract ``_run(*args, **kwargs)``, a public ``run`` that delegates to it,
    and an optional ``_arun`` behind ``arun``. Written from crewai's public
    interface, not from the package, which is not installed here.
    """
    from pydantic import BaseModel, Field

    class _NoArgs(BaseModel):
        pass

    class FakeCrewBaseTool(BaseModel, ABC):
        name: str
        description: str
        args_schema: type[BaseModel] = Field(default=_NoArgs)
        result_as_answer: bool = False

        @abstractmethod
        def _run(self, *args: Any, **kwargs: Any) -> Any: ...

        async def _arun(self, *args: Any, **kwargs: Any) -> Any:
            raise NotImplementedError

        def run(self, *args: Any, **kwargs: Any) -> Any:
            return self._run(*args, **kwargs)

        async def arun(self, *args: Any, **kwargs: Any) -> Any:
            return await self._arun(*args, **kwargs)

    return FakeCrewBaseTool
