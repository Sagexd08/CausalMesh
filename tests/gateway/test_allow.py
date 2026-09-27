"""Tests for allowed tool execution: the gate runs, the handler runs."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from causalmesh import CausalMesh, Tool

pytestmark = pytest.mark.unit


def _mesh(tmp_path: Path, owns: list[str] | None = None) -> CausalMesh:
    p = tmp_path / "causalmesh.yaml"
    owns_lines = "\n".join(f'              - "{o}"' for o in (owns or ["src/", "tests/"]))
    p.write_text(
        dedent(f"""\
        version: 1
        agent:
          id: coding-agent
        roles:
          - agent_id: coding-agent
            archetype: writer
            owns:
{owns_lines}
        policy:
          arm: C3
    """),
        encoding="utf-8",
    )
    return CausalMesh.from_config(p)


class TestAllowedCalls:
    def test_non_mutating_always_allowed(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(Tool(name="get", handler=lambda k: f"val:{k}", mutating=False))
        result = mesh.execute(agent_id="coding-agent", tool="get", arguments={"k": "x"})
        assert result.allowed
        assert result.value == "val:x"

    def test_mutating_on_owned_path_allowed(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path, owns=["src/"])
        executed: list[str] = []
        mesh.register_tool(
            Tool(
                name="write",
                handler=lambda path, content: executed.append(path),
                mutating=True,
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write",
            arguments={"path": "src/hello.py", "content": "pass"},
        )
        assert result.allowed
        assert result.executed
        assert executed == ["src/hello.py"]

    def test_default_agent_id_used(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        # Register a tool that doesn't need agent_id but verify via boundary
        mesh.register_tool(Tool(name="noop", handler=lambda: None, mutating=False))
        result = mesh.execute(tool="noop", arguments={})  # no explicit agent_id
        assert result.agent_id == "coding-agent"
        assert result.executed

    def test_returns_handler_value(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(Tool(name="add", handler=lambda a, b: a + b, mutating=False))
        result = mesh.execute(agent_id="coding-agent", tool="add", arguments={"a": 3, "b": 4})
        assert result.value == 7

    def test_handler_exception_gives_failed_result(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)

        def boom(**_: object) -> None:
            raise RuntimeError("oops")

        mesh.register_tool(Tool(name="explode", handler=boom, mutating=False))
        result = mesh.execute(agent_id="coding-agent", tool="explode", arguments={})
        assert result.failed
        assert not result.executed
        assert not result.denied
        assert "oops" in result.reason
