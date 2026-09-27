"""Tests for denial: the gate fires and the handler NEVER runs.

This is the most important invariant in Phase 1:

    DENIED ACTION == TOOL NEVER EXECUTED

Every test in this file proves some aspect of that property.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from causalmesh import CausalMesh, Tool

pytestmark = pytest.mark.unit


def _make_contract(tmp_path: Path, *, arm: str = "C3") -> Path:
    p = tmp_path / "causalmesh.yaml"
    p.write_text(
        dedent(f"""\
            version: 1
            agent:
              id: coding-agent
            roles:
              - agent_id: coding-agent
                archetype: writer
                owns:
                  - "src/"
              - agent_id: dba
                archetype: writer
                owns:
                  - "production/"
            policy:
              arm: {arm}
        """),
        encoding="utf-8",
    )
    return p


def _mesh(tmp_path: Path, arm: str = "C3") -> CausalMesh:
    return CausalMesh.from_config(_make_contract(tmp_path, arm=arm))


class TestHandlerNeverCalled:
    """The handler must be completely skipped on denial."""

    def test_handler_not_called_on_ownership_denial(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        sentinel: list[bool] = []
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content: sentinel.append(True),
                mutating=True,
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "production/database.sql", "content": "DROP TABLE users;"},
        )
        assert result.denied
        assert len(sentinel) == 0, "handler was called despite denial — INVARIANT VIOLATED"

    def test_handler_not_called_for_any_foreign_path(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        calls: list[str] = []
        mesh.register_tool(
            Tool(
                name="write",
                handler=lambda path, content: calls.append(path),
                mutating=True,
            )
        )
        for foreign_path in [
            "production/a.sql",
            "production/sub/b.sql",
        ]:
            result = mesh.execute(
                agent_id="coding-agent",
                tool="write",
                arguments={"path": foreign_path, "content": "x"},
            )
            assert result.denied, f"expected denial for {foreign_path}"
        assert len(calls) == 0


class TestDenialProperties:
    def test_denied_result_properties(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        assert result.denied is True
        assert result.allowed is False
        assert result.executed is False
        assert result.failed is False
        assert result.value is None

    def test_denied_result_has_nonempty_reason(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        assert result.reason != ""

    def test_denied_result_rule_is_ownership(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        assert result.rule == "ownership"

    def test_describe_produces_useful_output(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        desc = result.describe()
        assert "Action denied" in desc
        assert "coding-agent" in desc
        assert "write" in desc

    def test_denied_tool_name_in_result(self, tmp_path: Path) -> None:
        mesh = _mesh(tmp_path)
        mesh.register_tool(
            Tool(name="my_writer", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="my_writer",
            arguments={"path": "production/x", "content": "x"},
        )
        assert result.tool == "my_writer"
        assert result.agent_id == "coding-agent"

    def test_non_enforcing_arm_allows(self, tmp_path: Path) -> None:
        """C2 does not enforce; it records what it would have refused."""
        mesh = _mesh(tmp_path, arm="C2")
        sentinel: list[bool] = []
        mesh.register_tool(
            Tool(
                name="write",
                handler=lambda path, content: sentinel.append(True),
                mutating=True,
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        # C2 does not enforce; would have refused but allows
        assert result.allowed
        assert len(sentinel) == 1
