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

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from causalmesh.crypto.keys import KeyPair, SignatureError, load_identity_keys
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

# The run id is part of every event's signed identity, so a random default
# would make two identical sessions produce different chains.  A caller that
# keeps several chains side by side passes its own stable run_id.
_DEFAULT_RUN_ID = "sdk"


class CausalMesh:
    """The developer-facing CausalMesh session.

    One instance manages:

    - the loaded ``Contract`` (policy rules)
    - a ``ToolGateway`` (registered tools)
    - a ``LifecycleBoundary`` wired to the ``ContractGate``
    - a ``Relay`` for evidence recording

    Every agent that may call ``execute()`` needs a signing key, or its
    calls could not be recorded.  Keys are issued to the default agent,
    every ``agent_id`` under ``roles``, and anything passed in ``agents``.
    A call for any other agent raises ``UnknownAgentError`` before it runs.

    Where the keys come from, in order:

    1. ``identity.keys`` in the contract: one seed file per agent.
    2. ``seed``: derived per agent, so the signed chain is reproducible.
    3. Neither: a fresh random key per agent, as ``causalmesh serve`` does.
       Signatures then differ between sessions; the payloads do not.

    Args:
        agent_id:   Default agent id used when ``execute()`` is called
                    without an explicit ``agent_id``.
        contract:   A pre-loaded ``Contract`` object.  Use
                    ``CausalMesh.from_config()`` to load from a file.
        run_id:     Identifier for this session's evidence chain.  It is
                    signed into every event, so it defaults to a constant
                    rather than a random value.
        seed:       Master seed for deriving agent keys.  Keep it secret:
                    anyone holding it can sign as any agent.
        agents:     Additional agent ids to issue keys to.
    """

    def __init__(
        self,
        *,
        agent_id: str = "sdk-agent",
        contract: Contract,
        run_id: str | None = None,
        seed: bytes | None = None,
        agents: Iterable[str] = (),
        _sdk_config: SDKConfig | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._contract = contract
        self._run_id = run_id or _DEFAULT_RUN_ID
        self._sdk_config = _sdk_config

        agent_ids = sorted({agent_id, *(role.agent_id for role in contract.roles), *agents})
        self._relay, self._boundary, self._gate = _build_runtime(
            contract=contract,
            run_id=self._run_id,
            agent_ids=agent_ids,
            seed=seed,
        )

        def _identity_factory(aid: str) -> EventIdentity:
            return make_identity(aid, contract=contract, run_id=self._run_id)

        self._gateway = ToolGateway(
            boundary=self._boundary,
            relay=self._relay,
            agent_id=agent_id,
            identity_factory=_identity_factory,
            gate=self._gate,
        )

    # ------------------------------------------------------------------ #
    # Construction                                                        #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_config(
        cls,
        path: str | Path,
        *,
        run_id: str | None = None,
        seed: bytes | None = None,
        agents: Iterable[str] = (),
    ) -> CausalMesh:
        """Build a ``CausalMesh`` from a ``causalmesh.yaml`` file.

        ``run_id``, ``seed`` and ``agents`` are passed through to the
        constructor; see the class docstring.

        Raises:
            ConfigurationError: When the file is missing, invalid, or
                contains an unsupported policy arm, or when
                ``identity.keys`` lacks a key file for a declared agent.
        """
        try:
            contract, sdk_config = load_sdk_config(path)
        except ConfigurationError:
            raise
        except ContractError as exc:
            raise ConfigurationError(str(exc)) from exc

        agent_id = sdk_config.agent_id or "sdk-agent"
        try:
            return cls(
                agent_id=agent_id,
                contract=contract,
                run_id=run_id,
                seed=seed,
                agents=agents,
                _sdk_config=sdk_config,
            )
        except SignatureError as exc:
            raise ConfigurationError(str(exc)) from exc

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

    @property
    def agents(self) -> tuple[str, ...]:
        """Every agent id this session can record calls for."""
        return self._relay.actors

    @property
    def enforcing(self) -> bool:
        """Whether the gate acts on refusals.

        True only on arm C3.  On C0, C1 and C2 every call is allowed and a
        call C3 would refuse comes back with ``result.would_refuse`` set.
        """
        return self._contract.arm == "C3"

    def audit_events(self) -> list[dict[str, Any]]:
        """All events recorded in the relay, in chain order.

        One dict per recorded call.  A call whose result has
        ``recorded is False`` does not appear here.
        """
        return self._relay.records()

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
    agent_ids: list[str],
    seed: bytes | None,
) -> tuple[Relay, LifecycleBoundary, ContractGate]:
    """Assemble the relay, boundary, and gate for one SDK session.

    Uses the existing ``ContractGate`` (which wraps the existing
    ``PolicyGate`` / ``Gate``) — there is exactly one authorization path.
    """
    relay = Relay(
        run_id=run_id,
        keypairs=_keypairs(contract, agent_ids, seed),
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


def _keypairs(contract: Contract, agent_ids: list[str], seed: bytes | None) -> dict[str, KeyPair]:
    """One signing key per agent, sourced as ``tasks/runner.py`` does.

    ``identity.keys`` wins over ``seed``: an operator who declared external
    keys did so to stop participants sharing a derivation seed, and
    ``load_identity_keys`` refuses a partial set for the same reason.
    """
    if contract.identity_keys_dir is not None:
        return load_identity_keys(contract.identity_keys_dir, agent_ids=agent_ids)
    if seed is not None:
        return {agent: KeyPair.derive(seed, agent) for agent in agent_ids}
    return {agent: KeyPair.generate(agent) for agent in agent_ids}
