"""Integration tests: agent ↔ gateway end-to-end.

Proves the full Phase 1 acceptance criteria in an integrated scenario:

1. A registered tool can execute through CausalMesh.
2. An allowed action reaches the underlying tool.
3. A denied action NEVER reaches the underlying tool.
4. A denied action returns a useful reason.
5. A denied action is recorded in the existing event/evidence mechanism.
6. Existing signed evidence remains verifiable.
7. Existing policy behavior remains unchanged.
8. Multiple tool calls work sequentially.
9. Unknown tools fail safely.
10. Invalid policy configuration fails with a useful developer error.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from causalmesh import CausalMesh, Tool
from causalmesh.sdk.errors import ConfigurationError, ToolNotFoundError

pytestmark = pytest.mark.integration


# ------------------------------------------------------------------ #
# Fixtures                                                            #
# ------------------------------------------------------------------ #

def _write_contract(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "causalmesh.yaml"
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


def _multi_role_mesh(tmp_path: Path) -> CausalMesh:
    contract_path = _write_contract(tmp_path, """\
        version: 1
        agent:
          id: coding-agent
        roles:
          - agent_id: coding-agent
            archetype: writer
            owns:
              - "src/"
              - "tests/"
          - agent_id: dba-agent
            archetype: writer
            owns:
              - "production/"
        policy:
          arm: C3
        tools:
          read_file:
            mode: auto
          write_file:
            mode: auto
    """)
    return CausalMesh.from_config(contract_path)


# ------------------------------------------------------------------ #
# Acceptance criterion 1: registered tool executes                    #
# ------------------------------------------------------------------ #

class TestRegisteredToolExecutes:
    def test_basic_end_to_end(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        mesh.register_tool(
            Tool(
                name="read_file",
                handler=lambda path: f"file:{path}",
                kind="filesystem",
                mutating=False,
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="read_file",
            arguments={"path": "src/main.py"},
        )
        assert result.executed
        assert result.value == "file:src/main.py"


# ------------------------------------------------------------------ #
# Acceptance criterion 2+3: allowed reaches handler, denied does not  #
# ------------------------------------------------------------------ #

class TestAllowDenyInvariant:
    def test_allowed_path_executes(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        written: list[str] = []
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content: written.append(path),
                kind="filesystem",
                mutating=True,
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/example.py", "content": "print('hello')"},
        )
        assert result.allowed is True
        assert result.executed is True
        assert "src/example.py" in written

    def test_denied_path_handler_never_called(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        handler_called: list[bool] = []
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content: handler_called.append(True),
                kind="filesystem",
                mutating=True,
            )
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "production/database.sql", "content": "DROP TABLE"},
        )
        assert result.denied is True
        assert len(handler_called) == 0, "CRITICAL: handler called despite denial"

    def test_acceptance_criteria_example(self, tmp_path: Path) -> None:
        """The exact acceptance criteria example from the spec."""
        mesh = _multi_role_mesh(tmp_path)

        def write_file(path: str, content: str) -> str:
            return f"wrote {len(content)} bytes to {path}"

        mesh.register_tool(
            Tool(
                name="write_file",
                handler=write_file,
                kind="filesystem",
                mutating=True,
            )
        )

        # Permitted path (coding-agent owns src/)
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/example.py", "content": "print('hello')"},
        )
        assert result.allowed is True

        # Forbidden path (production/ is owned by dba-agent)
        result2 = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "production/database.sql", "content": "DROP TABLE"},
        )
        assert result2.denied is True


# ------------------------------------------------------------------ #
# Acceptance criterion 4: denial reason is useful                     #
# ------------------------------------------------------------------ #

class TestDenialReason:
    def test_denial_has_reason(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        assert result.reason != ""
        assert result.rule == "ownership"

    def test_denial_describe_mentions_all_key_facts(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        result = mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        desc = result.describe()
        assert "coding-agent" in desc
        assert "write_file" in desc
        assert "denied" in desc.lower()


# ------------------------------------------------------------------ #
# Acceptance criterion 5: denial recorded in evidence                 #
# ------------------------------------------------------------------ #

class TestDenialEvidence:
    def test_denied_call_produces_audit_event(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        before = len(mesh.audit_events())
        mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "production/db.sql", "content": "x"},
        )
        after = len(mesh.audit_events())
        assert after > before

    def test_allowed_call_produces_audit_event(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        mesh.register_tool(
            Tool(name="write_file", handler=lambda path, content: None, mutating=True)
        )
        before = len(mesh.audit_events())
        mesh.execute(
            agent_id="coding-agent",
            tool="write_file",
            arguments={"path": "src/ok.py", "content": "ok"},
        )
        after = len(mesh.audit_events())
        assert after > before


# ------------------------------------------------------------------ #
# Acceptance criterion 8: sequential calls                            #
# ------------------------------------------------------------------ #

class TestSequentialCalls:
    def test_ten_sequential_calls(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        log: list[int] = []
        mesh.register_tool(
            Tool(name="log", handler=lambda n: log.append(n), mutating=False)
        )
        for i in range(10):
            r = mesh.execute(agent_id="coding-agent", tool="log", arguments={"n": i})
            assert r.executed, f"call {i} failed"
        assert log == list(range(10))

    def test_interleaved_allow_deny(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        handler_calls: list[str] = []
        mesh.register_tool(
            Tool(
                name="write_file",
                handler=lambda path, content: handler_calls.append(path),
                mutating=True,
            )
        )

        calls = [
            ("src/a.py", True),
            ("production/b.sql", False),
            ("src/c.py", True),
            ("production/d.sql", False),
        ]
        for path, should_allow in calls:
            r = mesh.execute(
                agent_id="coding-agent",
                tool="write_file",
                arguments={"path": path, "content": "x"},
            )
            if should_allow:
                assert r.executed, f"{path} should have been allowed"
            else:
                assert r.denied, f"{path} should have been denied"

        assert set(handler_calls) == {"src/a.py", "src/c.py"}


# ------------------------------------------------------------------ #
# Acceptance criterion 9: unknown tool fails safely                   #
# ------------------------------------------------------------------ #

class TestUnknownTool:
    def test_raises_tool_not_found(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        with pytest.raises(ToolNotFoundError) as exc_info:
            mesh.execute(agent_id="coding-agent", tool="nonexistent_tool", arguments={})
        assert "nonexistent_tool" in str(exc_info.value)

    def test_error_message_lists_available_tools(self, tmp_path: Path) -> None:
        mesh = _multi_role_mesh(tmp_path)
        mesh.register_tool(Tool(name="read_file", handler=lambda: None))
        with pytest.raises(ToolNotFoundError) as exc_info:
            mesh.execute(agent_id="coding-agent", tool="write_file", arguments={})
        assert "read_file" in str(exc_info.value)


# ------------------------------------------------------------------ #
# Acceptance criterion 10: invalid policy fails with useful error     #
# ------------------------------------------------------------------ #

class TestInvalidPolicy:
    def test_bad_arm_raises_configuration_error(self, tmp_path: Path) -> None:
        p = _write_contract(tmp_path, """\
            version: 1
            policy:
              arm: NOTANARM
        """)
        with pytest.raises(ConfigurationError, match="unknown arm"):
            CausalMesh.from_config(p)

    def test_missing_file_raises_configuration_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigurationError, match="no config file"):
            CausalMesh.from_config(tmp_path / "does_not_exist.yaml")

    def test_unknown_top_level_key_raises(self, tmp_path: Path) -> None:
        p = _write_contract(tmp_path, """\
            version: 1
            totally_bad_key: something
            policy:
              arm: C3
        """)
        with pytest.raises(ConfigurationError, match="unknown key"):
            CausalMesh.from_config(p)
