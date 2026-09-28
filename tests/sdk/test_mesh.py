"""Tests for the CausalMesh public class.

Covers the main acceptance criteria from the Phase 1 spec:

1. A registered tool can execute through CausalMesh.
2. An allowed action reaches the underlying tool.
3. A denied action NEVER reaches the underlying tool.
4. A denied action returns a useful reason.
5. Multiple tool calls work sequentially.
6. Unknown tools fail safely.
7. Invalid policy fails with a useful developer error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.sdk.errors import ConfigurationError, ToolNotFoundError

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #


def _simple_contract(tmp_path: Path, *, arm: str = "C3", owns: list[str] | None = None) -> Path:
    p = tmp_path / "causalmesh.yaml"
    coding_owns = owns or ["src/"]
    # Build YAML manually with explicit indentation — no dedent tricks
    lines = [
        "version: 1",
        "agent:",
        "  id: coding-agent",
        "roles:",
        "  - agent_id: coding-agent",
        "    archetype: writer",
        "    owns:",
    ]
    for o in coding_owns:
        lines.append(f'      - "{o}"')
    lines += [
        "  - agent_id: other-agent",
        "    archetype: writer",
        "    owns:",
        '      - "protected/"',
        "policy:",
        f"  arm: {arm}",
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestFromConfig:
    def test_loads_from_yaml(self, tmp_path: Path) -> None:
        p = _simple_contract(tmp_path)
        mesh = CausalMesh.from_config(p)
        assert mesh.contract.arm == "C3"
        assert mesh.agent_id == "coding-agent"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError):
            CausalMesh.from_config(tmp_path / "missing.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "causalmesh.yaml"
        bad.write_text("{ bad yaml: [}}", encoding="utf-8")
        with pytest.raises(ConfigurationError):
            CausalMesh.from_config(bad)

    def test_default_run_id_is_stable_across_sessions(self, tmp_path: Path) -> None:
        """The run id is signed into every event, so it must not be random."""
        p = _simple_contract(tmp_path)
        assert CausalMesh.from_config(p).run_id == CausalMesh.from_config(p).run_id

    def test_run_id_explicit(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path), run_id="test-run-001")
        assert mesh.run_id == "test-run-001"


class TestToolRegistration:
    def test_register_single_tool(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        called = []
        mesh.register_tool(Tool(name="ping", handler=lambda: called.append(1), mutating=False))
        assert "ping" in mesh.registered_tools()

    def test_register_multiple_tools(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        for name in ("a", "b", "c"):
            mesh.register_tool(Tool(name=name, handler=lambda: None))
        assert set(mesh.registered_tools()) == {"a", "b", "c"}

    def test_reregister_overwrites(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        mesh.register_tool(Tool(name="t", handler=lambda: "v1"))
        mesh.register_tool(Tool(name="t", handler=lambda: "v2"))
        result = mesh.execute(agent_id="coding-agent", tool="t")
        assert result.value == "v2"

    def test_get_tool_retrieves_registered_tool(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        t = Tool(name="fetch", handler=lambda: None)
        mesh.register_tool(t)
        assert mesh.get_tool("fetch") is t

    def test_get_tool_raises_on_unknown(self, tmp_path: Path) -> None:
        from causalmesh.sdk.errors import ToolNotFoundError

        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        with pytest.raises(ToolNotFoundError, match="tool 'missing' is not registered"):
            mesh.get_tool("missing")


class TestAllowedExecution:
    """Allowed calls must reach the handler and return its value."""

    def test_non_mutating_call_always_allowed(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        mesh.register_tool(
            Tool(name="read", handler=lambda path: f"contents of {path}", mutating=False)
        )
        result = mesh.execute(agent_id="coding-agent", tool="read", arguments={"path": "README.md"})
        assert result.allowed
        assert result.executed
        assert not result.denied
        assert "README.md" in result.value

    def test_mutating_call_on_owned_path_allowed(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path, owns=["src/"]))
        written: list[str] = []
        mesh.register_tool(
            Tool(
                name="write_file", handler=lambda path, content: written.append(path), mutating=True
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/example.py", "content": "hello"},
        )
        assert result.allowed
        assert result.executed
        assert "src/example.py" in written

    def test_handler_return_value_exposed(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        mesh.register_tool(Tool(name="compute", handler=lambda x: x * 2, mutating=False))
        result = mesh.execute(agent_id="coding-agent", tool="compute", arguments={"x": 21})
        assert result.value == 42


class TestDeniedExecution:
    """Denied calls must never reach the handler."""

    def test_mutating_call_on_foreign_path_denied(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path, owns=["src/"]))
        handler_called: list[bool] = []
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content: handler_called.append(True),
                mutating=True,
            )
        )
        # "protected/" is owned by "other-agent", not "coding-agent"
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "protected/secret.sql", "content": "DROP TABLE"},
        )
        assert result.denied
        assert not result.allowed
        assert not result.executed
        # The MOST IMPORTANT INVARIANT: handler was never called
        assert len(handler_called) == 0

    def test_denial_reason_is_informative(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path, owns=["src/"]))
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "protected/data.sql", "content": "x"},
        )
        assert result.denied
        assert result.reason  # non-empty
        assert result.rule in {"ownership", "claim", "budget", "allowlist", "ceiling"}

    def test_describe_denial_contains_agent_and_tool(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path, owns=["src/"]))
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "protected/data.sql", "content": "x"},
        )
        description = result.describe()
        assert "coding-agent" in description
        assert "write_file" in description


class TestUnknownTool:
    def test_unknown_tool_raises(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        with pytest.raises(ToolNotFoundError, match="not registered"):
            mesh.execute(agent_id="coding-agent", tool="nonexistent")


class TestSequentialCalls:
    """Multiple tool calls work without interference."""

    def test_multiple_sequential_calls(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path))
        log: list[str] = []
        mesh.register_tool(Tool(name="log", handler=lambda msg: log.append(msg), mutating=False))

        for i in range(5):
            r = mesh.execute(agent_id="coding-agent", tool="log", arguments={"msg": f"call-{i}"})
            assert r.executed, f"call {i} should have executed"

        assert log == [f"call-{i}" for i in range(5)]

    def test_mix_of_allowed_and_denied(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path, owns=["src/"]))
        handler_calls: list[str] = []
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content: handler_calls.append(path),
                mutating=True,
            )
        )

        # Allowed: coding-agent owns src/
        r1 = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/ok.py", "content": "ok"},
        )
        # Denied: coding-agent doesn't own protected/
        r2 = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "protected/bad.sql", "content": "bad"},
        )
        # Allowed again
        r3 = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/also_ok.py", "content": "ok"},
        )

        assert r1.executed
        assert r2.denied
        assert r3.executed
        assert handler_calls == ["src/ok.py", "src/also_ok.py"]
        assert "protected/bad.sql" not in handler_calls


class TestBoundarySummary:
    def test_summary_counts_outcomes(self, tmp_path: Path) -> None:
        mesh = CausalMesh.from_config(_simple_contract(tmp_path, owns=["src/"]))
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/ok.py", "content": "ok"},
        )
        mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "protected/bad.sql", "content": "bad"},
        )
        summary = mesh.boundary_summary()
        assert summary["executed"] == 1
        assert summary["denied"] == 1
        assert summary["calls"] == 2
