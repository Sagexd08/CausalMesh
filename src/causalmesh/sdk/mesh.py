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

import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from causalmesh.crypto.keys import (
    KeyPair,
    PublicKeyRing,
    SignatureError,
    load_identity_keys,
)
from causalmesh.events.schema import EventIdentity
from causalmesh.hooks.lifecycle import LifecycleBoundary
from causalmesh.hooks.policy_gate import ContractGate
from causalmesh.policy.contract import Contract, ContractError
from causalmesh.policy.ledger import Ledger
from causalmesh.relay import NullDelivery, Relay

from ..gateway.gateway import ToolGateway
from ..gateway.result import GatewayResult
from ..gateway.tool import Tool
from .config import SDKConfig, load_sdk_config
from .errors import ConfigurationError, EvidenceError, EvidenceUnavailableError
from .evidence import (
    EvidenceStore,
    last_event_counter,
    load_evidence,
    resume_chain,
    write_evidence,
    write_public_keys,
)
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
        ledger:     Where spend and budget consumption is recorded. A contract
                    that declares a total (``usd_total``, ``tokens``, ...)
                    needs one: without it the gate refuses the spend, since a
                    total nothing records is a total nothing enforces.
        evidence_path: An append-only JSONL file the session writes every signed
                    record to (flushed and ``fsync``-ed per event).  If the file
                    already holds a chain it is verified against this session's
                    keys and continued, so the same ``seed=`` (or
                    ``identity.keys``) and ``run_id`` must be used on restart.
                    See ``causalmesh.sdk.evidence`` for the guarantees.
        recover_evidence: Repair a torn final line (an interrupted write): the
                    fragment moves to ``<file>.torn`` and the chain resumes
                    from the last whole record.  Off by default, so a torn
                    file is refused rather than silently trimmed.
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
        evidence_path: str | Path | None = None,
        recover_evidence: bool = False,
        _sdk_config: SDKConfig | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._contract = contract
        self._run_id = run_id or _DEFAULT_RUN_ID
        self._sdk_config = _sdk_config
        self._closed = False
        self._close_lock = threading.Lock()
        self._evidence: EvidenceStore | None = None

        agent_ids = sorted({agent_id, *(role.agent_id for role in contract.roles), *agents})
        if evidence_path is not None:
            self._evidence = EvidenceStore(evidence_path, recover=recover_evidence)
        try:
            self._relay, self._boundary, self._gate = _build_runtime(
                contract=contract,
                run_id=self._run_id,
                agent_ids=agent_ids,
                seed=seed,
                ledger=ledger,
                store=self._evidence,
            )
            resumed = 0
            if self._evidence is not None:
                resumed = resume_chain(self._relay, self._evidence, run_id=self._run_id)
        except BaseException:
            if self._evidence is not None:
                self._evidence.close()
            raise

        def _identity_factory(aid: str) -> EventIdentity:
            return make_identity(aid, contract=contract, run_id=self._run_id)

        self._gateway = ToolGateway(
            boundary=self._boundary,
            relay=self._relay,
            agent_id=agent_id,
            identity_factory=_identity_factory,
            gate=self._gate,
            ledger=ledger,
        )
        if resumed:
            self._gateway.resume_event_counter(last_event_counter(self._relay.records()))

    # ------------------------------------------------------------------ #
    # Construction                                                       #
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
        evidence_path: str | Path | None = None,
        recover_evidence: bool = False,
    ) -> CausalMesh:
        """Build a ``CausalMesh`` from a ``causalmesh.yaml`` file.

        ``run_id``, ``seed``, ``agents``, ``ledger``, ``evidence_path`` and
        ``recover_evidence`` are passed through to the constructor; see the
        class docstring.

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
                evidence_path=evidence_path,
                recover_evidence=recover_evidence,
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

        Returns:
            ``GatewayResult`` describing the outcome.

        Raises:
            ToolNotFoundError: When ``tool`` is not registered.
        """
        aid = agent_id or self._agent_id
        self._require_evidence_writable()
        return self._gateway.execute(
            aid,
            tool,
            arguments,
            paths=paths,
            now_us=now_us,
        )

    async def execute_async(
        self,
        *,
        agent_id: str | None = None,
        tool: str,
        arguments: dict[str, Any] | None = None,
        paths: tuple[str, ...] | None = None,
        now_us: int | None = None,
    ) -> GatewayResult:
        """Execute an asynchronous tool call through the policy gate.

        See ``execute()`` for argument details.
        """
        aid = agent_id or self._agent_id
        self._require_evidence_writable()
        return await self._gateway.execute_async(
            agent_id=aid,
            tool=tool,
            arguments=arguments,
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
    # Evidence persistence and export                                     #
    # ------------------------------------------------------------------ #

    @property
    def evidence_path(self) -> Path | None:
        """The file this session persists to, or ``None`` when memory-only."""
        return self._evidence.path if self._evidence is not None else None

    @property
    def evidence_recovery(self) -> dict[str, Any] | None:
        """What ``recover_evidence`` repaired on open, or ``None`` if nothing.

        ``{"torn_bytes", "preserved_in", "records_kept"}``: the size of the
        interrupted final write, where it was kept, and how many whole
        records survived.
        """
        return self._evidence.recovery if self._evidence is not None else None

    @property
    def evidence_head(self) -> str:
        """The chain head hash right now: what an external anchor should hold.

        Truncating a chain from the end leaves a shorter chain that still
        verifies.  Only a copy of the head, kept somewhere the writer cannot
        reach, shows that it happened.
        """
        return self._relay.head_hash

    def key_ring(self) -> PublicKeyRing:
        """The public keys this session signs with."""
        return self._relay.key_ring()

    def export_evidence(self, path: str | Path) -> Path:
        """Write this session's whole chain to `path` as JSONL, atomically.

        Works for a memory-only session and for a persisted one (it is then a
        copy; the live file is never the destination).  Read it back with
        ``load_evidence`` and verify it with ``causalmesh verify --evidence``.
        """
        destination = Path(path)
        if self._evidence is not None and _same_file(destination, self._evidence.path):
            raise EvidenceError(
                f"{destination} is this session's live evidence file; export to another path"
            )
        return write_evidence(destination, self._relay.records())

    def export_public_keys(self, directory: str | Path) -> list[Path]:
        """Write one ``<agent_id>.pub`` per agent into `directory`.

        The format ``causalmesh verify --keys`` reads.  Only public keys are
        written.  A ring exported from the machine that also holds the log is
        not independent trust: take it away before the session, or from
        wherever the keys were issued.
        """
        return write_public_keys(self.key_ring(), directory)

    @staticmethod
    def load_evidence(path: str | Path, *, allow_torn_tail: bool = False) -> list[dict[str, Any]]:
        """Read an evidence file back into records; see ``sdk.evidence.load_evidence``."""
        return load_evidence(path, allow_torn_tail=allow_torn_tail)

    def close(self) -> None:
        """Release the evidence file and its lock.  Safe to call twice."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        if self._evidence is not None:
            self._evidence.close()

    def __enter__(self) -> CausalMesh:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _require_evidence_writable(self) -> None:
        """Refuse to run a tool whose record could not be written.

        Checked before the gate, so the handler never runs after the evidence
        file has failed or the session has been closed.
        """
        if self._evidence is None:
            return
        if self._closed:
            raise EvidenceUnavailableError(
                f"this session is closed; {self._evidence.path} is no longer being written"
            )
        failure = self._evidence.failure
        if failure is not None:
            raise EvidenceUnavailableError(failure)


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
    store: EvidenceStore | None = None,
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


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return a.absolute() == b.absolute()
