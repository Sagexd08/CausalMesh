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

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from causalmesh.crypto.keys import KeyPair, SignatureError, load_identity_keys
from causalmesh.events.schema import EventIdentity, utc_now_micros
from causalmesh.hooks.lifecycle import LifecycleBoundary
from causalmesh.hooks.policy_gate import ContractGate
from causalmesh.policy.contract import Contract, ContractError
from causalmesh.policy.ledger import Ledger
from causalmesh.relay import NullDelivery, Relay
from causalmesh.relay.store import ChainStore, StoreError

from ..gateway.clock import DEFAULT_CLOCK_BASE_US, DEFAULT_CLOCK_TICK_US
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

_CHAIN_FILE = "chain.jsonl"
_KEYRING_FILE = "keyring.json"
_RUN_FILE = "run.json"


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
        ledger:     Where spend and budget consumption is recorded. A contract
                    that declares a total (``usd_total``, ``tokens``, ...)
                    needs one: without it the gate refuses the spend, since a
                    total nothing records is a total nothing enforces.
        clock_base_us, clock_tick_us:
                    The logical clock that stamps the signed chain: the n-th
                    call is signed at ``base + n * tick``, so two sessions
                    with the same seed and the same calls have the same head
                    hash.  The wall-clock time of each call goes in the
                    unsigned envelope of ``export()``.  A lease or window is
                    therefore measured in calls: see ``now_us``.
        persist_to: A directory to append the chain to as it is written
                    (``chain.jsonl``, flushed per event) with ``keyring.json``
                    beside it, so a crash loses nothing already recorded.
                    Must not already hold a chain.  ``export()`` is still how
                    a ``causalmesh verify --run`` artifact is produced.
    """

    def __init__(
        self,
        *,
        agent_id: str = "sdk-agent",
        contract: Contract,
        run_id: str | None = None,
        seed: bytes | None = None,
        agents: Iterable[str] = (),
        ledger: Ledger | None = None,
        clock_base_us: int = DEFAULT_CLOCK_BASE_US,
        clock_tick_us: int = DEFAULT_CLOCK_TICK_US,
        persist_to: str | Path | None = None,
        _sdk_config: SDKConfig | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._contract = contract
        self._run_id = run_id or _DEFAULT_RUN_ID
        self._sdk_config = _sdk_config

        agent_ids = sorted({agent_id, *(role.agent_id for role in contract.roles), *agents})
        store: ChainStore | None = None
        if persist_to is not None:
            try:
                store = ChainStore(Path(persist_to) / _CHAIN_FILE)
            except StoreError as exc:
                raise ConfigurationError(str(exc)) from exc
        self._store = store
        self._relay, self._boundary, self._gate = _build_runtime(
            contract=contract,
            run_id=self._run_id,
            agent_ids=agent_ids,
            seed=seed,
            ledger=ledger,
            store=store,
        )
        if persist_to is not None:
            _write_json(Path(persist_to) / _KEYRING_FILE, self._relay.key_ring().to_dict())

        def _identity_factory(aid: str) -> EventIdentity:
            return make_identity(aid, contract=contract, run_id=self._run_id)

        self._gateway = ToolGateway(
            boundary=self._boundary,
            relay=self._relay,
            agent_id=agent_id,
            identity_factory=_identity_factory,
            gate=self._gate,
            ledger=ledger,
            clock_base_us=clock_base_us,
            clock_tick_us=clock_tick_us,
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
        ledger: Ledger | None = None,
        clock_base_us: int = DEFAULT_CLOCK_BASE_US,
        clock_tick_us: int = DEFAULT_CLOCK_TICK_US,
        persist_to: str | Path | None = None,
    ) -> CausalMesh:
        """Build a ``CausalMesh`` from a ``causalmesh.yaml`` file.

        ``run_id``, ``seed``, ``agents``, ``ledger``, the clock arguments and
        ``persist_to`` are passed through to the constructor; see the class
        docstring.

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
                ledger=ledger,
                clock_base_us=clock_base_us,
                clock_tick_us=clock_tick_us,
                persist_to=persist_to,
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

    def get_tool(self, name: str) -> Tool:
        """Fetch a registered tool by name."""
        return self._gateway.get_tool(name)

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
        annotations: Mapping[str, str] | None = None,
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
                        claim rules).  When omitted, extracted by the
                        ResourceResolver based on the Tool's resource_args.
            now_us:     Timestamp override for deterministic tests.
            annotations: Extra string fields recorded on the call's event
                        (signed, so reproducible values only).  See
                        ``ToolGateway.execute``.

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
            annotations=annotations,
        )

    async def execute_async(
        self,
        *,
        agent_id: str | None = None,
        tool: str,
        arguments: dict[str, Any] | None = None,
        paths: tuple[str, ...] | None = None,
        now_us: int | None = None,
        annotations: Mapping[str, str] | None = None,
    ) -> GatewayResult:
        """Execute an asynchronous tool call through the policy gate.

        See ``execute()`` for argument details.
        """
        aid = agent_id or self._agent_id
        return await self._gateway.execute_async(
            agent_id=aid,
            tool=tool,
            arguments=arguments,
            paths=paths,
            now_us=now_us,
            annotations=annotations,
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

    @property
    def now_us(self) -> int:
        """The session's logical time: what the last call was signed at.

        ``clock_base_us`` before the first call.  Acquire a lease at this
        value, not at the wall clock, or it expires on a clock the gate never
        reads.
        """
        return self._gateway.clock.now_us

    # ------------------------------------------------------------------ #
    # Export                                                              #
    # ------------------------------------------------------------------ #

    def export(self, directory: str | Path) -> dict[str, Path]:
        """Write this session's evidence where ``causalmesh verify --run`` reads it.

        Writes ``run.json`` (the signed chain, plus an unsigned ``envelope``)
        and ``keyring.json`` (the public keys, never a private one).  Verify
        with ``causalmesh verify --run <directory>``; the verifier prefers
        ``keyring.json`` to the keys embedded in the records, so a chain
        re-signed with a different key is rejected.

        The envelope holds what must not be signed: the wall-clock time of
        the export and of each call, and a description of the logical clock.
        Editing it changes nothing the verifier checks.  ``keyring.json``
        is only as trustworthy as the channel it travels on: hand it to the
        verifier separately from the run, or pin its fingerprint.

        Raises:
            FileExistsError: When ``directory`` already holds a ``run.json``
                or ``keyring.json``.  Raw evidence is written once.
        """
        destination = Path(directory)
        run_path = destination / _RUN_FILE
        keyring_path = destination / _KEYRING_FILE
        ring = self._relay.key_ring()
        ring_text = _json_text(ring.to_dict())
        if run_path.exists():
            raise FileExistsError(
                f"{run_path} already exists. Evidence is written once; export to a new directory."
            )
        # `persist_to` already wrote this ring; the same ring again is fine,
        # a different one is someone else's evidence.
        if keyring_path.exists() and keyring_path.read_text(encoding="utf-8") != ring_text:
            raise FileExistsError(
                f"{keyring_path} already exists with different keys. Export to a new directory."
            )

        chain = self._relay.records()
        artifact: dict[str, Any] = {
            "agents": list(self._relay.actors),
            "arm": self._contract.arm,
            "chain": chain,
            "envelope": {
                "clock": self._gateway.clock.to_dict(),
                "exported_at_us": utc_now_micros(),
                "note": "Unsigned. Wall-clock values are for the reader; nothing here is verified.",
                "wall_time_us_by_event": self._gateway.wall_times(),
            },
            "events": len(chain),
            "head_hash": self._relay.head_hash,
            "key_ring_fingerprint": ring.fingerprint(),
            "run_id": self._run_id,
        }
        destination.mkdir(parents=True, exist_ok=True)
        # Keys first: a half-written export must not look verifiable against a
        # ring that is missing.
        keyring_path.write_text(ring_text, encoding="utf-8")
        _write_json(run_path, artifact)
        return {"keyring": keyring_path, "run": run_path}

    def close(self) -> None:
        """Close the persisted chain file, when ``persist_to`` was given."""
        if self._store is not None:
            self._store.close()


# ------------------------------------------------------------------ #
# Internal assembly                                                    #
# ------------------------------------------------------------------ #


def _build_runtime(
    *,
    contract: Contract,
    run_id: str,
    agent_ids: list[str],
    seed: bytes | None,
    ledger: Ledger | None = None,
    store: ChainStore | None = None,
) -> tuple[Relay, LifecycleBoundary, ContractGate]:
    """Assemble the relay, boundary, and gate for one SDK session.

    Uses the existing ``ContractGate`` (which wraps the existing
    ``PolicyGate`` / ``Gate``) — there is exactly one authorization path.
    """
    relay = Relay(
        run_id=run_id,
        keypairs=_keypairs(contract, agent_ids, seed),
        store=store,
        delivery=NullDelivery(),  # SDK runs: no peer fan-out needed
    )

    gate = ContractGate.build(
        contract,
        run_id=run_id,
        registry=None,  # No claim registry in Phase 1 SDK mode
        enforcing=contract.arm == "C3",
        ledger=ledger,
        require_ledger=True,
    )

    boundary = LifecycleBoundary(gate=gate)

    return relay, boundary, gate


def _json_text(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_text(payload), encoding="utf-8")


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
