"""The controlled tool API and the lifecycle boundary (spec §12, §13).

The properties that matter most, and get the most attention:

- **Every tool resolves paths through the workspace.** A tool that took a raw
  path would be a hole straight through the L2 containment layer.
- **The gate runs before execution.** A denied write must not have touched
  the file, so checking after opening it would already be too late.
- **Every call is recorded**, denials and failures included. A denial with no
  record is invisible to the analysis, and C3's enforcement cost would be
  understated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.claims import ClaimRegistry
from causalmesh.hooks import (
    MUTATING_TOOLS,
    TOOL_EVENT_TYPES,
    AllowAllGate,
    ClaimGate,
    GateDecision,
    HookContext,
    LifecycleBoundary,
    ToolCall,
    ToolOutcome,
    ToolResult,
    gate_for_arm,
)
from causalmesh.isolation import PathEscapeError, Workspace
from causalmesh.tools import TOOL_NAMES, Toolbox, ToolError

pytestmark = pytest.mark.unit

RUN = "run_001"
SECOND = 1_000_000


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    workspace = Workspace.create(base=tmp_path / "ws", run_id=RUN, agent_id="agent_a")
    (workspace.root / "src").mkdir()
    (workspace.root / "src" / "schema.py").write_text("# original\n", encoding="utf-8")
    return workspace


@pytest.fixture
def toolbox(workspace: Workspace) -> Toolbox:
    return Toolbox(workspace)


@pytest.fixture
def peer(tmp_path: Path) -> Path:
    other = Workspace.create(base=tmp_path / "ws", run_id=RUN, agent_id="agent_b")
    secret = other.root / "secret.py"
    secret.write_text("# agent_b's work\n", encoding="utf-8")
    return secret


class TestToolSurface:
    def test_every_declared_tool_exists(self, toolbox: Toolbox) -> None:
        assert all(hasattr(toolbox, name) for name in TOOL_NAMES)

    def test_the_tool_count_is_pinned(self) -> None:
        """The documented surface must match the implemented one.

        `api.py`, `docs/PLAN.md` and `docs/IDEA.md` all state this number,
        and all three once said twelve while eleven were implemented — the
        docstring even listed eleven under the word "twelve". Pinning it
        here means adding or removing a tool forces the documentation to be
        updated in the same change rather than drifting silently.
        """
        assert len(TOOL_NAMES) == 11
        assert len(set(TOOL_NAMES)) == 11, "a tool name is duplicated"

    def test_every_tool_maps_to_an_event_type(self) -> None:
        # An unmapped tool would execute without being recordable.
        assert set(TOOL_NAMES) == set(TOOL_EVENT_TYPES)

    def test_mutating_tools_are_a_subset_of_the_api(self) -> None:
        assert set(TOOL_NAMES) > MUTATING_TOOLS

    def test_there_is_no_general_shell_tool(self, toolbox: Toolbox) -> None:
        # A shell would void every isolation claim in docs/security.md.
        assert not any(
            hasattr(toolbox, name) for name in ("shell", "exec", "system", "eval")
        )


class TestReads:
    def test_read_file_returns_content(self, toolbox: Toolbox) -> None:
        assert toolbox.read_file("src/schema.py") == "# original\n"

    def test_reading_a_missing_file_is_an_error(self, toolbox: Toolbox) -> None:
        with pytest.raises(ToolError, match="does not exist"):
            toolbox.read_file("nope.py")

    def test_list_files_returns_relative_paths(self, toolbox: Toolbox) -> None:
        assert toolbox.list_files() == ["src/schema.py"]

    def test_list_files_can_scope_to_a_subdirectory(self, toolbox: Toolbox) -> None:
        assert toolbox.list_files("src") == ["src/schema.py"]


class TestWrites:
    def test_write_file_creates_parent_directories(self, toolbox: Toolbox) -> None:
        assert toolbox.write_file("a/b/c.py", "x = 1\n") == 6
        assert toolbox.read_file("a/b/c.py") == "x = 1\n"

    def test_create_file_refuses_an_existing_path(self, toolbox: Toolbox) -> None:
        # CREATE and WRITE are different events (§16); conflating them would
        # blur "I added this" with "I replaced this".
        with pytest.raises(ToolError, match="already exists"):
            toolbox.create_file("src/schema.py", "x")

    def test_modify_file_replaces_an_exact_substring(self, toolbox: Toolbox) -> None:
        assert toolbox.modify_file("src/schema.py", "original", "modified") == 1
        assert toolbox.read_file("src/schema.py") == "# modified\n"

    def test_modify_file_refuses_when_the_target_is_absent(
        self, toolbox: Toolbox
    ) -> None:
        with pytest.raises(ToolError, match="not found"):
            toolbox.modify_file("src/schema.py", "absent text", "x")

    def test_delete_file_removes_it(self, toolbox: Toolbox, workspace: Workspace) -> None:
        toolbox.delete_file("src/schema.py")
        assert not (workspace.root / "src" / "schema.py").exists()

    def test_rename_file_moves_it(self, toolbox: Toolbox) -> None:
        toolbox.rename_file("src/schema.py", "src/renamed.py")
        assert toolbox.list_files() == ["src/renamed.py"]

    def test_rename_refuses_to_overwrite(self, toolbox: Toolbox) -> None:
        toolbox.create_file("src/other.py", "y")
        with pytest.raises(ToolError, match="already exists"):
            toolbox.rename_file("src/schema.py", "src/other.py")


class TestPathContainment:
    """Every tool must resolve through the workspace — no exceptions."""

    @pytest.mark.parametrize(
        ("tool", "arguments"),
        [
            ("read_file", {"path": "../agent_b/secret.py"}),
            ("write_file", {"path": "../agent_b/secret.py", "content": "x"}),
            ("create_file", {"path": "../agent_b/injected.py", "content": "x"}),
            ("modify_file", {"path": "../agent_b/secret.py", "old": "a", "new": "b"}),
            ("delete_file", {"path": "../agent_b/secret.py"}),
            ("list_files", {"subdirectory": "../agent_b"}),
        ],
    )
    def test_no_tool_can_reach_a_peer_workspace(
        self, toolbox: Toolbox, peer: Path, tool: str, arguments: dict
    ) -> None:
        with pytest.raises(PathEscapeError):
            getattr(toolbox, tool)(**arguments)

    def test_rename_cannot_write_outside_via_its_destination(
        self, toolbox: Toolbox, peer: Path
    ) -> None:
        # Both ends are resolved; checking only the source would leave the
        # destination as an escape.
        with pytest.raises(PathEscapeError):
            toolbox.rename_file("src/schema.py", "../agent_b/stolen.py")

    def test_a_peer_file_is_untouched_by_a_refused_write(
        self, toolbox: Toolbox, peer: Path
    ) -> None:
        original = peer.read_bytes()
        with pytest.raises(PathEscapeError):
            toolbox.write_file("../agent_b/secret.py", "overwritten")
        assert peer.read_bytes() == original


class TestCommandExecution:
    def test_an_allowlisted_command_runs(self, toolbox: Toolbox) -> None:
        result = toolbox.run_command(["python", "-c", "print('hello')"])
        assert result.exit_code == 0
        assert "hello" in result.stdout

    def test_a_command_runs_inside_the_workspace(
        self, toolbox: Toolbox, workspace: Workspace
    ) -> None:
        result = toolbox.run_command(["python", "-c", "import os; print(os.getcwd())"])
        assert Path(result.stdout.strip()).resolve() == workspace.root

    def test_a_non_allowlisted_command_is_refused(self, toolbox: Toolbox) -> None:
        # An allowlist, not a denylist: a denylist promises to have imagined
        # every dangerous command.
        with pytest.raises(ToolError, match="not allowlisted"):
            toolbox.run_command(["curl", "https://example.com"])

    def test_a_shell_string_is_refused(self, toolbox: Toolbox) -> None:
        # shell=True would let `&&` or redirection escape containment.
        with pytest.raises(ToolError, match="not a shell string"):
            toolbox.run_command("python -c 'print(1)'")

    def test_an_empty_command_is_refused(self, toolbox: Toolbox) -> None:
        with pytest.raises(ToolError, match="non-empty"):
            toolbox.run_command([])

    def test_a_failing_command_returns_its_exit_code(self, toolbox: Toolbox) -> None:
        # A non-zero exit is data, not an exception: the harness decides what
        # it means for task success (§38).
        assert toolbox.run_command(["python", "-c", "raise SystemExit(3)"]).exit_code == 3

    def test_a_timeout_is_recorded_not_raised(self, toolbox: Toolbox) -> None:
        # §22 treats a hung command as an injectable failure the run survives.
        result = toolbox.run_command(
            ["python", "-c", "import time; time.sleep(30)"], timeout=1
        )
        assert result.timed_out
        assert result.exit_code == -1

    def test_the_environment_is_scrubbed(self, toolbox: Toolbox) -> None:
        """Inheriting the operator's environment would break §3.

        An API key or a proxy setting leaking through would also make runs
        depend on whose shell launched them.
        """
        import os

        os.environ["CAUSALMESH_LEAK_CANARY"] = "should-not-appear"
        try:
            result = toolbox.run_command(
                ["python", "-c", "import os; print(os.environ.get('CAUSALMESH_LEAK_CANARY', 'ABSENT'))"]
            )
            assert result.stdout.strip() == "ABSENT"
        finally:
            del os.environ["CAUSALMESH_LEAK_CANARY"]

    def test_subprocesses_get_a_deterministic_hash_seed(self, toolbox: Toolbox) -> None:
        result = toolbox.run_command(
            ["python", "-c", "import os; print(os.environ['PYTHONHASHSEED'])"]
        )
        assert result.stdout.strip() == "0"


class TestLifecycleBoundary:
    def test_an_allowed_call_executes(self) -> None:
        boundary = LifecycleBoundary(gate=AllowAllGate())
        result = boundary.invoke(
            ToolCall(tool="write_file", agent_id="agent_a", paths=("a.py",)),
            lambda call: "done",
            now_us=0,
        )
        assert result.outcome == ToolOutcome.EXECUTED
        assert result.value == "done"

    def test_a_denied_call_never_reaches_the_tool(self) -> None:
        """§20: the refusal happens before the tool function runs at all."""
        executed = []

        class DenyGate:
            def check(self, call: ToolCall, now_us: int) -> GateDecision:
                return GateDecision(allowed=False, reason="denied for this test")

        boundary = LifecycleBoundary(gate=DenyGate())
        result = boundary.invoke(
            ToolCall(tool="write_file", agent_id="agent_a", paths=("a.py",)),
            lambda call: executed.append(call),
            now_us=0,
        )
        assert result.outcome == ToolOutcome.DENIED
        assert executed == [], "the tool ran despite being denied"

    def test_reads_do_not_consult_the_gate(self) -> None:
        # Gating reads would make C3 differ from C2 in more than write
        # enforcement, which is the factor §20 defines.
        consulted = []

        class RecordingGate:
            def check(self, call: ToolCall, now_us: int) -> GateDecision:
                consulted.append(call.tool)
                return GateDecision(allowed=True, reason="ok")

        boundary = LifecycleBoundary(gate=RecordingGate())
        boundary.invoke(
            ToolCall(tool="read_file", agent_id="agent_a", paths=("a.py",)),
            lambda call: "content",
            now_us=0,
        )
        assert consulted == []

    def test_a_tool_failure_is_recorded_not_raised(self) -> None:
        # §81: a failure is evidence; the run continues and keeps context.
        boundary = LifecycleBoundary()
        result = boundary.invoke(
            ToolCall(tool="read_file", agent_id="agent_a", paths=("missing.py",)),
            lambda call: (_ for _ in ()).throw(ToolError("no such file")),
            now_us=0,
        )
        assert result.outcome == ToolOutcome.FAILED
        assert "no such file" in (result.error or "")

    @pytest.mark.parametrize(
        ("gate", "expected"),
        [
            (AllowAllGate(), ToolOutcome.EXECUTED),
            (None, ToolOutcome.EXECUTED),
        ],
    )
    def test_every_outcome_is_recorded(self, gate, expected: ToolOutcome) -> None:
        boundary = LifecycleBoundary(gate=gate) if gate else LifecycleBoundary()
        boundary.invoke(
            ToolCall(tool="write_file", agent_id="agent_a", paths=("a.py",)),
            lambda call: None,
            now_us=0,
        )
        assert len(boundary.results) == 1
        assert boundary.results[0].outcome == expected

    def test_denied_and_failed_calls_are_both_recorded(self) -> None:
        class DenyGate:
            def check(self, call: ToolCall, now_us: int) -> GateDecision:
                return GateDecision(allowed=False, reason="no")

        boundary = LifecycleBoundary(gate=DenyGate())
        boundary.invoke(
            ToolCall(tool="write_file", agent_id="agent_a", paths=("a.py",)),
            lambda call: None,
            now_us=0,
        )
        boundary.invoke(
            ToolCall(tool="read_file", agent_id="agent_a"),
            lambda call: (_ for _ in ()).throw(RuntimeError("boom")),
            now_us=0,
        )
        summary = boundary.summary()
        assert summary["denied"] == 1
        assert summary["failed"] == 1
        assert summary["calls"] == 2

    def test_denied_and_failed_are_distinct_outcomes(self) -> None:
        # Collapsing them would make enforcement look like unreliability.
        assert ToolOutcome.DENIED != ToolOutcome.FAILED

    def test_hooks_run_in_order_around_the_call(self) -> None:
        order = []
        boundary = LifecycleBoundary(
            pre_hooks=[lambda ctx: order.append("pre")],
            post_hooks=[lambda ctx, result: order.append("post")],
        )
        boundary.invoke(
            ToolCall(tool="read_file", agent_id="agent_a"),
            lambda call: order.append("tool"),
            now_us=0,
        )
        assert order == ["pre", "tool", "post"]

    def test_post_hooks_run_even_for_denied_calls(self) -> None:
        # Accounting must see the denial, or coordination cost is undercounted.
        seen: list[ToolResult] = []

        class DenyGate:
            def check(self, call: ToolCall, now_us: int) -> GateDecision:
                return GateDecision(allowed=False, reason="no")

        boundary = LifecycleBoundary(
            gate=DenyGate(), post_hooks=[lambda ctx, result: seen.append(result)]
        )
        boundary.invoke(
            ToolCall(tool="write_file", agent_id="agent_a", paths=("a.py",)),
            lambda call: None,
            now_us=0,
        )
        assert len(seen) == 1
        assert seen[0].outcome == ToolOutcome.DENIED

    def test_injection_accounting_flows_from_the_hook_context(self) -> None:
        """L3 of the isolation model: coordination bytes are counted per call."""

        def inject(context: HookContext) -> None:
            context.injected_events = 3
            context.injected_bytes = 512

        boundary = LifecycleBoundary(pre_hooks=[inject])
        result = boundary.invoke(
            ToolCall(tool="read_file", agent_id="agent_a"), lambda call: None, now_us=0
        )
        assert result.injected_events == 3
        assert result.injected_bytes == 512

    def test_latency_percentiles_are_none_when_unmeasured(self) -> None:
        assert LifecycleBoundary().summary()["hook_latency_p50_us"] is None


class TestGateSelection:
    @pytest.mark.parametrize("arm", ["C0", "C1", "C2"])
    def test_unenforced_arms_get_allow_all(self, arm: str) -> None:
        gate = gate_for_arm(arm, registry=None, run_id=RUN)
        assert isinstance(gate, AllowAllGate)

    def test_c3_gets_the_claim_gate(self, tmp_path: Path) -> None:
        with ClaimRegistry(tmp_path / "claims.db") as registry:
            gate = gate_for_arm("C3", registry=registry, run_id=RUN)
            assert isinstance(gate, ClaimGate)

    def test_c3_without_a_registry_is_refused(self) -> None:
        # Otherwise the run would be indistinguishable from C2 while claiming
        # to be enforced, and the C2→C3 contrast would measure nothing.
        with pytest.raises(ValueError, match="requires a claim registry"):
            gate_for_arm("C3", registry=None, run_id=RUN)

    def test_an_unknown_arm_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown arm"):
            gate_for_arm("C7", registry=None, run_id=RUN)


class TestClaimGate:
    def test_a_held_path_is_refused(self, tmp_path: Path) -> None:
        with ClaimRegistry(tmp_path / "claims.db") as registry:
            registry.acquire(
                claim_id="c1",
                path="src/schema.py",
                agent_id="agent_a",
                run_id=RUN,
                now_us=0,
                duration_us=120 * SECOND,
            )
            gate = ClaimGate(registry=registry, run_id=RUN)
            decision = gate.check(
                ToolCall(tool="write_file", agent_id="agent_b", paths=("src/schema.py",)),
                SECOND,
            )
            assert not decision.allowed
            assert decision.holder_agent == "agent_a"
            assert decision.blocked_path == "src/schema.py"

    def test_the_holder_is_allowed(self, tmp_path: Path) -> None:
        with ClaimRegistry(tmp_path / "claims.db") as registry:
            registry.acquire(
                claim_id="c1",
                path="src/schema.py",
                agent_id="agent_a",
                run_id=RUN,
                now_us=0,
                duration_us=120 * SECOND,
            )
            gate = ClaimGate(registry=registry, run_id=RUN)
            assert gate.check(
                ToolCall(tool="write_file", agent_id="agent_a", paths=("src/schema.py",)),
                SECOND,
            ).allowed

    def test_any_blocked_path_stops_a_multi_path_call(self, tmp_path: Path) -> None:
        # A partially-applied operation would leave the workspace in a state
        # no event described.
        with ClaimRegistry(tmp_path / "claims.db") as registry:
            registry.acquire(
                claim_id="c1",
                path="src/b.py",
                agent_id="agent_a",
                run_id=RUN,
                now_us=0,
                duration_us=120 * SECOND,
            )
            gate = ClaimGate(registry=registry, run_id=RUN)
            decision = gate.check(
                ToolCall(
                    tool="write_file", agent_id="agent_b", paths=("src/a.py", "src/b.py")
                ),
                SECOND,
            )
            assert not decision.allowed
            assert decision.blocked_path == "src/b.py"
