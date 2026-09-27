"""The main public entry point for Phase 1.

``CausalMesh`` is the object a developer instantiates.  It wires together:

    - ``Contract`` (policy rules, loaded from causalmesh.yaml)
    - ``ContractGate`` (the existing policy enforcement plane)
    - ``LifecycleBoundary`` (the existing lifecycle control point)
    - ``Relay`` (the existing event/evidence system)
    - ``ToolGateway`` (the new developer-facing tool registry)

Nothing here duplicates policy logic.  The gate, the boundary, and the
relay are the *same* objects the existing experimental harness uses.  The
SDK is a thin wrapper that makes assembling them a one-liner.

Typical use::

    from causalmesh import CausalMesh, Tool

    mesh = CausalMesh.from_config("causalmesh.yaml")

    mesh.register_tool(
        Tool(name="write_file", handler=write_file, kind="filesystem", mutating=True)
    )

    result = mesh.execute(
        agent_id="coding-agent",
        tool="write_file",
        arguments={"path": "src/example.py", "content": "print('hello')"},
    )

    if result.denied:
        print(result.describe())

Architecture::

    CausalMesh.execute()
        ↓
    ToolGateway.execute()
        ↓
    LifecycleBoundary.invoke()
        ↓  (gate.check() runs here — handler not called yet)
    ContractGate.check()  ← existing policy + claim enforcement
        ↓
    ALLOW → handler(**arguments)
    DENY  → GatewayResult(denied=True) — handler never called
        ↓
    Relay.ingest()  ← evidence recorded either way
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity
from causalmesh.hooks.lifecycle import LifecycleBoundary
from causalmesh.hooks.policy_gate import ContractGate
from causalmesh.policy.contract import Contract, ContractError
from causalmesh.relay import NullDelivery, Relay

from ..gateway.gateway import ToolGateway
from ..gateway.result import GatewayResult
from ..gateway.tool import Tool
from .config import SDKConfig, load_sdk_config
from .errors import ConfigurationError
from .identity import make_identity

__all__ = ["CausalMesh"]

_SDK_SEED = b"causalmesh-sdk-phase1"


class CausalMesh:
    """The developer-facing CausalMesh session.

    One instance manages:

    - the loaded ``Contract`` (policy rules)
    - a ``ToolGateway`` (registered tools)
    - a ``LifecycleBoundary`` wired to the ``ContractGate``
    - a ``Relay`` for evidence recording

    Args:
        agent_id:   Default agent id used when ``execute()`` is called
                    without an explicit ``agent_id``.
        contract:   A pre-loaded ``Contract`` object.  Use
                    ``CausalMesh.from_config()`` to load from a file.
        run_id:     Stable identifier for this session's evidence chain.
                    Auto-generated when omitted.
    """

    def __init__(
        self,
        *,
        agent_id: str = "sdk-agent",
        contract: Contract,
        run_id: str | None = None,
        _sdk_config: SDKConfig | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._contract = contract
        self._run_id = run_id or f"sdk-{uuid.uuid4().hex[:12]}"
        self._sdk_config = _sdk_config

        self._relay, self._boundary, self._gate = _build_runtime(
            contract=contract,
            run_id=self._run_id,
            agent_id=agent_id,
        )

        def _identity_factory(aid: str) -> EventIdentity:
            return make_identity(aid, contract=contract, run_id=self._run_id)

        self._gateway = ToolGateway(
            boundary=self._boundary,
            relay=self._relay,
            agent_id=agent_id,
            identity_factory=_identity_factory,
        )

    # ------------------------------------------------------------------ #
    # Construction                                                        #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(cls, path: str | Path, *, run_id: str | None = None) -> CausalMesh:
        """Build a ``CausalMesh`` from a ``causalmesh.yaml`` file.

        Raises:
            ConfigurationError: When the file is missing, invalid, or
                contains an unsupported policy arm.
        """
        try:
            contract, sdk_config = load_sdk_config(path)
        except ConfigurationError:
            raise
        except ContractError as exc:
            raise ConfigurationError(str(exc)) from exc

        agent_id = sdk_config.agent_id or "sdk-agent"
        return cls(
            agent_id=agent_id,
            contract=contract,
            run_id=run_id,
            _sdk_config=sdk_config,
        )

    # ------------------------------------------------------------------ #
    # Tool registration                                                   #
    # ------------------------------------------------------------------ #

    def register_tool(self, tool: Tool) -> None:
        """Register a tool with the gateway.

        Example::

            mesh.register_tool(
                Tool(name="write_file", handler=fn, kind="filesystem", mutating=True)
            )
        """
        self._gateway.register(tool)

    def registered_tools(self) -> list[str]:
        """Names of all registered tools."""
        return self._gateway.registered_tools()

    # ------------------------------------------------------------------ #
    # Execution                                                           #
    # ------------------------------------------------------------------ #

    def execute(
        self,
        *,
        agent_id: str | None = None,
        tool: str,
        arguments: dict[str, Any] | None = None,
        paths: tuple[str, ...] | None = None,
        now_us: int | None = None,
    ) -> GatewayResult:
        """Execute a tool call through the policy gate.

        The gate is consulted **before** the handler is invoked.  A
        denied call returns a ``GatewayResult`` with ``denied=True``
        and is recorded in the evidence chain.  The handler is never
        called for denied actions.

        Args:
            agent_id:   Overrides the session's default agent id.
            tool:       Name of a registered tool.
            arguments:  Keyword arguments forwarded to the handler.
            paths:      Paths the call touches (used by the ownership /
                        claim rules).  When omitted, extracted from
                        ``arguments["path"]`` when present.
            now_us:     Timestamp override for deterministic tests.

        Returns:
            ``GatewayResult`` describing the outcome.

        Raises:
            ToolNotFoundError: When ``tool`` is not registered.
        """
        aid = agent_id or self._agent_id
        return self._gateway.execute(
            aid,
            tool,
            arguments,
            paths=paths,
            now_us=now_us,
        )

    # ------------------------------------------------------------------ #
    # Inspection                                                          #
    # ------------------------------------------------------------------ #

    @property
    def contract(self) -> Contract:
        """The loaded policy contract."""
        return self._contract

    @property
    def run_id(self) -> str:
        """The unique run identifier for this session's evidence chain."""
        return self._run_id

    @property
    def agent_id(self) -> str:
        """Default agent id for this session."""
        return self._agent_id

    def audit_events(self) -> list[Any]:
        """All events recorded in the relay (in order).

        Returns dicts from the in-memory chain store — one per recorded call.
        """
        return list(self._relay._store.records())  # type: ignore[attr-defined]

    def boundary_summary(self) -> dict[str, Any]:
        """Per-outcome counts and hook latency from the lifecycle boundary."""
        return self._boundary.summary()


# ------------------------------------------------------------------ #
# Internal assembly                                                    #
# ------------------------------------------------------------------ #


def _build_runtime(
    *,
    contract: Contract,
    run_id: str,
    agent_id: str,
) -> tuple[Relay, LifecycleBoundary, ContractGate]:
    """Assemble the relay, boundary, and gate for one SDK session.

    Uses the existing ``ContractGate`` (which wraps the existing
    ``PolicyGate`` / ``Gate``) — there is exactly one authorization path.
    """
    # Derive a key pair for the agent so the relay can sign events.
    keypair = KeyPair.derive(_SDK_SEED, agent_id)

    relay = Relay(
        run_id=run_id,
        keypairs={agent_id: keypair},
        delivery=NullDelivery(),  # SDK runs: no peer fan-out needed
    )

    gate = ContractGate.build(
        contract,
        run_id=run_id,
        registry=None,  # No claim registry in Phase 1 SDK mode
        enforcing=contract.arm == "C3",
    )

    boundary = LifecycleBoundary(gate=gate)

    return relay, boundary, gate
