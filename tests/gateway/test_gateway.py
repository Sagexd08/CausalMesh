"""Tests for ToolGateway: registration and routing."""

from __future__ import annotations

import pytest

from causalmesh.crypto.keys import KeyPair
from causalmesh.gateway import GatewayResult, Tool, ToolGateway
from causalmesh.hooks.lifecycle import AllowAllGate, GateDecision, LifecycleBoundary, ToolCall
from causalmesh.relay import NullDelivery, Relay

pytestmark = pytest.mark.unit

_SEED = b"gateway-test-seed"
_AGENT = "test-agent"
_RUN = "run-001"


def _make_relay() -> Relay:
    return Relay(
        run_id=_RUN,
        keypairs={_AGENT: KeyPair.derive(_SEED, _AGENT)},
        delivery=NullDelivery(),
    )


def _make_gateway(gate: object | None = None) -> ToolGateway:
    relay = _make_relay()
    boundary = LifecycleBoundary(gate=gate or AllowAllGate())
    return ToolGateway(boundary=boundary, relay=relay, agent_id=_AGENT)


class TestToolRegistration:
    def test_register_and_list(self) -> None:
        gw = _make_gateway()
        gw.register(Tool(name="foo", handler=lambda: None))
        assert "foo" in gw.registered_tools()

    def test_register_multiple(self) -> None:
        gw = _make_gateway()
        for name in ("a", "b", "c"):
            gw.register(Tool(name=name, handler=lambda: None))
        assert gw.registered_tools() == ["a", "b", "c"]

    def test_invalid_type_raises(self) -> None:
        gw = _make_gateway()
        with pytest.raises(TypeError):
            gw.register("not a tool")  # type: ignore[arg-type]


class TestExecuteBasics:
    def test_unknown_tool_raises(self) -> None:
        from causalmesh.sdk.errors import ToolNotFoundError

        gw = _make_gateway()
        with pytest.raises(ToolNotFoundError):
            gw.execute(_AGENT, "nonexistent", {})

    def test_allowed_returns_gateway_result(self) -> None:
        gw = _make_gateway()
        gw.register(Tool(name="noop", handler=lambda: "ok", mutating=False))
        result = gw.execute(_AGENT, "noop", {})
        assert isinstance(result, GatewayResult)
        assert result.executed
        assert result.value == "ok"

    def test_handler_receives_arguments(self) -> None:
        gw = _make_gateway()
        received: list = []
        gw.register(Tool(name="echo", handler=lambda x, y: received.append((x, y)), mutating=False))
        gw.execute(_AGENT, "echo", {"x": 1, "y": 2})
        assert received == [(1, 2)]


class TestPathExtraction:
    def test_path_from_arguments(self) -> None:
        _make_gateway()
        call_paths: list = []

        class _CapturingGate:
            def check(self, call: ToolCall, now_us: int) -> GateDecision:
                call_paths.append(call.paths)
                return GateDecision(allowed=True, reason="ok")

        relay = _make_relay()
        boundary = LifecycleBoundary(gate=_CapturingGate())
        gw2 = ToolGateway(boundary=boundary, relay=relay, agent_id=_AGENT)
        gw2.register(Tool(name="write", handler=lambda path, content: None, mutating=True))
        gw2.execute(_AGENT, "write", {"path": "src/x.py", "content": "y"})
        assert call_paths[0] == ("src/x.py",)

    def test_explicit_paths_used(self) -> None:
        gw = _make_gateway()
        gw.register(Tool(name="write", handler=lambda content: None, mutating=True))
        result = gw.execute(_AGENT, "write", {"content": "x"}, paths=("explicit/path.py",))
        assert result.executed
