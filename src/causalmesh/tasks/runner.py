"""Executing one task under one arm (spec §71, §79).

This assembles the whole runtime — workspaces, relay, gate, channels,
executors, mock agents — drives the lifecycle, and returns the outcome with
its evidence. It is the piece the scheduler (§79) will call once per run and
the piece the §37 quality gate calls to prove a task is coordination
sensitive.

Keeping assembly in one place matters for the experiment, not just for
tidiness: every arm must be constructed the same way, differing only in the
delivery policy, the gate and the channel. Three separate call sites
building runtimes would eventually differ in a fourth way that nobody
noticed.
"""

from __future__ import annotations

import asyncio
import functools
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents import AgentContext, AgentIdentity, MockAgent, Scenario
from ..channels import MetadataChannel, NullChannel, Room, TranscriptChannel
from ..channels.base import CoordinationChannel
from ..claims import ClaimRegistry
from ..crypto.keys import KeyPair, load_identity_keys
from ..edges import CausalEdge, RelationshipType
from ..events.schema import EventIdentity, EventType
from ..hooks import LifecycleBoundary, gate_for_arm
from ..isolation import Workspace, build_run_workspaces
from ..policy import Contract
from ..relay import ChainStore, Relay, policy_for_arm
from ..relevance import AgentInterests
from ..tools import Toolbox, ToolExecutor
from ..tools.api import _INHERITED_ENVIRONMENT
from .definition import ContestedMerge, TaskDefinition
from .merge3 import merge_three_way
from .outcome import (
    AcceptanceDecision,
    TaskOutcome,
    decide_acceptance,
    evaluate_outcome,
    workspace_digest,
)

__all__ = ["RunConfig", "RunResult", "execute_task", "integration_test_preflight"]

DEFAULT_MAX_TURNS = 20
DEFAULT_TICK_US = 1_000_000
DEFAULT_LEASE_US = 120 * 1_000_000


@dataclass(frozen=True)
class RunConfig:
    """Everything that varies between runs of the same task.

    `master_seed` drives key derivation, so two runs with the same seed
    produce byte-identical signatures (§40, §84). It is explicit rather than
    defaulted because a run whose seed nobody recorded cannot be reproduced.
    """

    experiment_id: str
    run_id: str
    arm: str
    master_seed: bytes
    base_time_us: int = 1_700_000_000_000_000
    max_turns: int = DEFAULT_MAX_TURNS
    tick_us: int = DEFAULT_TICK_US
    lease_us: int = DEFAULT_LEASE_US
    window: int = 8
    operator_id: str = "unknown"
    machine_id: str = "unknown"
    git_commit: str = "unknown"
    contract_path: str | None = None
    checkpoint_handler: Any = None
    delivery_mode: str | None = None
    """Fan-out policy for the informed arms: None (the default) is whatever
    the arm prescribes, broadcast; "path_scoped" installs `PathScopedDelivery`
    with interests taken from the task's declared roles (spec section 86).
    C0 is isolated whatever this says."""

    def to_dict(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "arm": self.arm,
            "base_time_us": self.base_time_us,
            "experiment_id": self.experiment_id,
            "git_commit": self.git_commit,
            "lease_us": self.lease_us,
            "machine_id": self.machine_id,
            "max_turns": self.max_turns,
            "operator_id": self.operator_id,
            "run_id": self.run_id,
            "tick_us": self.tick_us,
            "window": self.window,
        }
        # Recorded only when set, so a run that never chose a delivery mode
        # serialises exactly as it did before the option existed.
        if self.delivery_mode is not None:
            record["delivery_mode"] = self.delivery_mode
        return record


@dataclass
class RunResult:
    """Everything one run produced.

    A failed run returns one of these too (§81): a failure is evidence, not
    garbage, so the chain, the summaries and the outcome are all present
    whatever happened.
    """

    run_id: str
    arm: str
    task_id: str
    task_hash: str
    outcome: TaskOutcome
    decision: AcceptanceDecision
    records: list[dict[str, Any]]
    head_hash: str | None
    agent_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    workspace_digests: dict[str, dict[str, str]] = field(default_factory=dict)
    claim_history: list[dict[str, Any]] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)
    relay_summary: dict[str, Any] = field(default_factory=dict)
    boundary_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate_summary: dict[str, Any] = field(default_factory=dict)
    edges: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    # True only when the run was cancelled mid-flight (the scheduler's
    # whole-run watchdog) and this result is what had been done by then. A
    # result with `interrupted=True` is partial evidence: `outcome` describes
    # the half-finished workspace and says nothing about whether the agents
    # would have succeeded.
    interrupted: bool = False
    # Contested paths the content-level merge could not resolve; `None` when the
    # task does not merge (`ContestedMerge.LAST_WRITER`), which is "not measured"
    # and must not be read as "no conflicts".
    merge_conflicts: list[str] | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome.succeeded

    def coordination_bytes(self) -> int:
        return sum(
            summary["coordination"]["coordination_bytes"]
            for summary in self.agent_summaries.values()
        )

    def to_dict(self) -> dict[str, Any]:
        record = {
            "agent_summaries": self.agent_summaries,
            "arm": self.arm,
            "boundary_summaries": self.boundary_summaries,
            "claim_history": self.claim_history,
            "coordination_bytes": self.coordination_bytes(),
            "decision": self.decision.to_dict(),
            "denials": self.denials,
            "edges": self.edges,
            "error": self.error,
            "events": len(self.records),
            "gate": self.gate_summary,
            "head_hash": self.head_hash,
            "interrupted": self.interrupted,
            "outcome": self.outcome.to_dict(),
            "relay_summary": self.relay_summary,
            "run_id": self.run_id,
            "task_hash": self.task_hash,
            "task_id": self.task_id,
            "workspace_digests": self.workspace_digests,
        }
        # Only when the task merges, so a result that never merged serialises
        # exactly as it did before the field existed.
        if self.merge_conflicts is not None:
            record["merge_conflicts"] = list(self.merge_conflicts)
        return record


def _make_channel(
    arm: str,
    agent_id: str,
    *,
    room: Room,
    window: int,
    owns: frozenset[str],
    depends_on: frozenset[str],
) -> CoordinationChannel:
    """Build the channel for one agent under one arm.

    C3 gets the same channel as C2 — the arms differ by enforcement alone,
    so giving C3 a different representation would confound the contrast.
    """
    if arm == "C0":
        return NullChannel(agent_id)
    if arm == "C1":
        return TranscriptChannel(agent_id, room)
    return MetadataChannel(
        agent_id,
        arm=arm,
        window=window,
        interests=AgentInterests(agent_id=agent_id, owned_paths=owns, dependency_paths=depends_on),
    )


def _gate_for(config: RunConfig, *, registry: Any, contract: Any = None):
    """The gate this run installs, and why.

    Without a contract the arms install their own gate: `AllowAllGate` for
    C0, C1 and C2, `ClaimGate` for C3. That is the experiment's factor, and
    it stays the default because the C2 to C3 contrast is only clean if the
    two arms differ by exactly one thing.

    With a contract, `ContractGate` is installed instead. It can also refuse
    on ownership, allowlists, ceilings and budgets, and it keeps the arm's
    enforcement semantics: C3 enforces, the others reach a verdict and allow
    anyway so the counterfactual stays measurable.

    `contract`, when given, is the already-loaded `Contract` for
    `config.contract_path` -- `execute_task` loads it once, ahead of this
    call, so `identity.keys` can be resolved before keypairs are built.
    """
    if config.contract_path is None:
        return gate_for_arm(config.arm, registry=registry, run_id=config.run_id)

    from ..hooks.policy_gate import ContractGate
    from ..policy import Contract

    return ContractGate.build(
        contract if contract is not None else Contract.load(config.contract_path),
        run_id=config.run_id,
        registry=registry,
        checkpoint_handler=config.checkpoint_handler,
        enforcing=config.arm == "C3",
    )


async def execute_task(
    task: TaskDefinition,
    config: RunConfig,
    *,
    workspace_root: Path,
    fixtures_root: Path,
    chain_path: Path | None = None,
    preserve_evidence_on_cancel: bool = False,
) -> RunResult:
    """Run one task under one arm and return the result with its evidence.

    Follows the §79 loop: prepare isolated workspaces, initialize agents and
    the relay, run the task, collect coordination and claims, run the
    success check, and return everything.

    `preserve_evidence_on_cancel` is how the scheduler's whole-run watchdog
    interrupts a run without losing it. Off (the default), a cancellation
    propagates as it always did. On, a cancellation that lands while agents
    are running is caught at the agent loop, the chain so far is sealed the
    normal way (verdicts, then an acceptance decision, all at the fixed
    post-run time, so no wall-clock value enters the signed chain) and a
    `RunResult` with `interrupted=True` is returned. The cancellation is
    consumed on purpose: the caller asked for partial evidence, not for an
    exception that would discard it. Cancellation is cooperative, so it can
    only land where an agent awaits.
    """
    scenario = Scenario.from_dict(task.scenario)
    agent_ids = list(task.agent_ids)

    workspaces = build_run_workspaces(
        base=workspace_root,
        run_id=config.run_id,
        agent_ids=agent_ids,
        fixture=Path(fixtures_root) / task.fixture,
    )

    contract = Contract.load(config.contract_path) if config.contract_path is not None else None

    if contract is not None and contract.identity_keys_dir is not None:
        keypairs = load_identity_keys(contract.identity_keys_dir, agent_ids=agent_ids)
    else:
        keypairs = {agent: KeyPair.derive(config.master_seed, agent) for agent in agent_ids}

    if contract is not None:
        keypairs["policy_gate"] = KeyPair.derive(config.master_seed, "policy_gate")
        if contract.checkpoints:
            keypairs["checkpoint"] = KeyPair.derive(config.master_seed, "checkpoint")
    keypairs["integration_test"] = KeyPair.derive(config.master_seed, "integration_test")
    keypairs["acceptance"] = KeyPair.derive(config.master_seed, "acceptance")
    claims = (
        ClaimRegistry(workspace_root / f"{config.run_id}_claims.db") if config.arm == "C3" else None
    )
    store = ChainStore(chain_path) if chain_path is not None else ChainStore()

    relay = Relay(
        run_id=config.run_id,
        keypairs=keypairs,
        store=store,
        delivery=policy_for_arm(
            config.arm,
            mode=config.delivery_mode,
            interests={
                role.agent_id: frozenset(role.owns | role.depends_on) for role in task.roles
            },
        ),
        claims=claims,
        participants=agent_ids,
    )
    gate = _gate_for(config, registry=claims, contract=contract)
    room = Room(config.run_id, task.task_id)

    agents: dict[str, MockAgent] = {}
    boundaries: dict[str, LifecycleBoundary] = {}
    for agent_id in agent_ids:
        role = task.role_for(agent_id)
        identity = AgentIdentity(
            experiment_id=config.experiment_id,
            task_id=task.task_id,
            run_id=config.run_id,
            agent_id=agent_id,
            arm=config.arm,
            operator_id=config.operator_id,
            machine_id=config.machine_id,
            model_id="mock",
            model_version="1",
            seed=int.from_bytes(config.master_seed[:8], "big"),
            git_commit=config.git_commit,
        )
        boundary = LifecycleBoundary(gate=gate)
        boundaries[agent_id] = boundary
        agents[agent_id] = MockAgent(
            identity,
            script=scenario.agents[agent_id],
            executor=ToolExecutor(
                agent_id=agent_id,
                identity=identity.to_event_identity(),
                toolbox=Toolbox(workspaces[agent_id]),
                boundary=boundary,
                relay=relay,
            ),
            channel=_make_channel(
                config.arm,
                agent_id,
                room=room,
                window=config.window,
                owns=role.owns,
                depends_on=role.depends_on,
            ),
            tick_us=config.tick_us,
        )

    if claims is not None:
        for agent_id in agent_ids:
            for index, path in enumerate(sorted(task.role_for(agent_id).owns)):
                claims.acquire(
                    claim_id=f"{config.run_id}_{agent_id}_{index}",
                    path=path,
                    agent_id=agent_id,
                    run_id=config.run_id,
                    now_us=config.base_time_us,
                    duration_us=config.lease_us,
                )

    error: str | None = None
    interrupted = False
    try:
        for agent in agents.values():
            await agent.initialize()

        for turn in range(config.max_turns):
            active = [a for a in agents.values() if not (a.turns and a.turns[-1].finished)]
            if not active:
                break
            for agent in active:
                context = AgentContext(
                    turn=turn, now_us=config.base_time_us + turn * config.tick_us
                )
                await agent.observe(context)
                await agent.plan(context)
                await agent.act(context)

        summaries = {agent_id: await agent.finalize() for agent_id, agent in agents.items()}
    except asyncio.CancelledError:
        if not preserve_evidence_on_cancel:
            raise
        interrupted = True
        error = "interrupted: run cancelled before the agents finished"
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()
        summaries = {agent_id: agent.summary() for agent_id, agent in agents.items()}
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        summaries = {agent_id: agent.summary() for agent_id, agent in agents.items()}

    integrated, merge_conflicts = _integrate_workspaces(
        task,
        workspaces,
        destination=workspace_root / f"{config.run_id}_integrated",
        records=relay.records(),
        base_root=Path(fixtures_root) / task.fixture,
    )
    exit_code = _run_integration_test(task, integrated)
    outcome = evaluate_outcome(
        task.success,
        workspace=integrated,
        test_exit_code=exit_code,
        merge_conflicts=merge_conflicts,
    )

    post_run_time_us = config.base_time_us + config.max_turns * config.tick_us

    edges: list[dict[str, Any]] = []

    try:
        if config.contract_path is not None:
            policy_identity = EventIdentity(
                experiment_id=config.experiment_id,
                task_id=task.task_id,
                run_id=config.run_id,
                agent_id="policy_gate",
                arm=config.arm,
            )
            for index, verdict in enumerate(gate.verdicts):
                ingested = relay.ingest(
                    event_id=f"{config.run_id}_verdict_{index}",
                    agent_id="policy_gate",
                    event_type=EventType.POLICY_VERDICT,
                    identity=policy_identity,
                    timestamp_us=post_run_time_us,
                    payload=verdict.to_dict(),
                )
                if not ingested.accepted:
                    raise RuntimeError(
                        f"policy verdict {index} of {len(gate.verdicts)} could not "
                        f"be recorded on the chain: {ingested.reason}"
                    )

            checkpoint_verdicts = [
                v for v in gate.verdicts if v.detail.get("checkpoint") is not None
            ]
            if checkpoint_verdicts:
                checkpoint_identity = EventIdentity(
                    experiment_id=config.experiment_id,
                    task_id=task.task_id,
                    run_id=config.run_id,
                    agent_id="checkpoint",
                    arm=config.arm,
                )
                for index, verdict in enumerate(checkpoint_verdicts):
                    ingested = relay.ingest(
                        event_id=f"{config.run_id}_checkpoint_{index}",
                        agent_id="checkpoint",
                        event_type=EventType.CHECKPOINT_DECIDED,
                        identity=checkpoint_identity,
                        timestamp_us=post_run_time_us,
                        payload=verdict.to_dict(),
                    )
                    if not ingested.accepted:
                        raise RuntimeError(
                            f"checkpoint decision {index} of {len(checkpoint_verdicts)} could "
                            f"not be recorded on the chain: {ingested.reason}"
                        )

            refused_verdict_ids = [
                f"{config.run_id}_verdict_{index}"
                for index, verdict in enumerate(gate.verdicts)
                if verdict.refused
            ]
            denied_event_ids = [
                record["event"]["event_id"]
                for record in relay.records()
                if record["event"]["event_type"] == "FAILURE"
                and record["event"]["payload"].get("outcome") == "denied"
            ]
            if len(refused_verdict_ids) != len(denied_event_ids):
                raise RuntimeError(
                    f"{len(refused_verdict_ids)} refused verdicts but "
                    f"{len(denied_event_ids)} denied events; cannot pair them "
                    "positionally"
                )
            for verdict_id, denied_id in zip(refused_verdict_ids, denied_event_ids, strict=True):
                edges.append(
                    CausalEdge(
                        from_event_id=denied_id,
                        to_event_id=verdict_id,
                        relationship=RelationshipType.REQUIRED,
                    ).to_dict()
                )

        # The harness's own integration-test run becomes a chain event so the
        # acceptance decision has a real event to point at. The payload is
        # reproducible by construction: the task's fixed command and the exit
        # code (None when the test never ran, recorded as `ran: false` rather
        # than as a confident 0). Output, duration and the workspace path are
        # deliberately absent -- they differ from run to run.
        integration_test_event_id = f"{config.run_id}_integration_test"
        ingested = relay.ingest(
            event_id=integration_test_event_id,
            agent_id="integration_test",
            event_type=EventType.INTEGRATION_TEST_RESULT,
            identity=EventIdentity(
                experiment_id=config.experiment_id,
                task_id=task.task_id,
                run_id=config.run_id,
                agent_id="integration_test",
                arm=config.arm,
            ),
            timestamp_us=post_run_time_us,
            payload={
                "command": list(task.success.integration_test),
                "exit_code": exit_code,
                "ran": exit_code is not None,
            },
        )
        if not ingested.accepted:
            raise RuntimeError(
                f"integration test result could not be recorded on the chain: {ingested.reason}"
            )

        decision = decide_acceptance(outcome, interrupted=interrupted)
        acceptance_identity = EventIdentity(
            experiment_id=config.experiment_id,
            task_id=task.task_id,
            run_id=config.run_id,
            agent_id="acceptance",
            arm=config.arm,
        )
        ingested = relay.ingest(
            event_id=f"{config.run_id}_acceptance",
            agent_id="acceptance",
            event_type=EventType.ACCEPTANCE_DECIDED,
            identity=acceptance_identity,
            timestamp_us=post_run_time_us,
            payload=decision.to_dict(),
        )
        if not ingested.accepted:
            raise RuntimeError(
                f"acceptance decision could not be recorded on the chain: {ingested.reason}"
            )
        # `decide_acceptance` reads `outcome`, which was built from this exit
        # code, so the dependency is real. It is REQUIRED, not CAUSED: the
        # decision has a second input (the divergence-marker check on the
        # integrated workspace) that is not a chain event.
        edges.append(
            CausalEdge(
                from_event_id=f"{config.run_id}_acceptance",
                to_event_id=integration_test_event_id,
                relationship=RelationshipType.REQUIRED,
                note=(
                    "acceptance requires the integration test result; "
                    "the divergence check is its other input and is not a chain event"
                ),
            ).to_dict()
        )

        result = RunResult(
            run_id=config.run_id,
            arm=config.arm,
            task_id=task.task_id,
            task_hash=task.content_hash(),
            outcome=outcome,
            decision=decision,
            records=relay.records(),
            head_hash=relay.head_hash,
            agent_summaries=summaries,
            workspace_digests={
                agent_id: workspace_digest(workspace) for agent_id, workspace in workspaces.items()
            },
            claim_history=(
                [c.to_dict() for c in claims.history(run_id=config.run_id)] if claims else []
            ),
            denials=claims.denials(run_id=config.run_id) if claims else [],
            gate_summary=gate.to_dict() if hasattr(gate, "to_dict") else {},
            edges=edges,
            relay_summary=relay.summary(),
            boundary_summaries={
                agent_id: boundary.summary() for agent_id, boundary in boundaries.items()
            },
            error=error,
            interrupted=interrupted,
            merge_conflicts=merge_conflicts,
        )
    finally:
        store.close()
        if claims is not None:
            claims.close()

    return result


def _integrate_workspaces(
    task: TaskDefinition,
    workspaces: dict[str, Workspace],
    *,
    destination: Path,
    records: list[dict[str, Any]] | None = None,
    base_root: Path | None = None,
) -> tuple[Workspace, list[str] | None]:
    """Merge the agents' workspaces into the shared codebase they represent.

    Returns the integrated workspace and the contested paths the merge could
    not resolve: `None` under `ContestedMerge.LAST_WRITER` (nothing was merged,
    so nothing is known about conflicts), a possibly empty sorted list under
    `THREE_WAY`. `base_root` is the fixture the agents started from and is
    required for `THREE_WAY`.

    Ownership decides: each file comes from the agent whose role declares
    it, since that is the agent the task made responsible for it and the
    same rule the claim registry enforces under C3. Files nobody owns are
    taken from any agent that has them, which is safe because an unowned
    file only differs if some agent wrote outside its remit — and that
    shows up as a divergence in `workspace_digests`.

    This makes the outcome a property of the agents' *combined* work.
    Judging a single workspace would score whether one agent's local view
    is self-consistent, which is not the question the experiment asks.
    """
    destination.mkdir(parents=True, exist_ok=True)
    merged = Workspace(agent_id="__integrated__", root=destination.resolve(), run_id=task.task_id)

    owner_of = {path: role.agent_id for role in task.roles for path in role.owns}

    contested = set(task.contested_paths)
    for path in contested:
        owner_of.pop(path, None)

    for agent_id in sorted(workspaces):
        workspace = workspaces[agent_id]
        for relative in workspace.list_files():
            if relative in owner_of or relative in contested:
                continue
            target = merged.resolve(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(workspace.resolve(relative).read_bytes())

    three_way = task.contested_merge == ContestedMerge.THREE_WAY
    if three_way and base_root is None:
        raise ValueError(
            f"{task.task_id}: contested_merge=three_way needs the fixture to merge against"
        )
    merge_conflicts: list[str] | None = [] if three_way else None

    for relative in sorted(contested):
        if three_way:
            assert base_root is not None and merge_conflicts is not None
            if not _merge_contested(relative, workspaces, base_root, merged):
                merge_conflicts.append(relative)
            continue
        writer = _last_writer(relative, records or [])
        candidates = [writer] if writer else sorted(workspaces)
        for agent_id in candidates:
            candidate_workspace = workspaces.get(agent_id)
            if candidate_workspace is None or not candidate_workspace.contains(relative):
                continue
            workspace = candidate_workspace
            origin = workspace.resolve(relative)
            if not origin.is_file():
                continue
            target = merged.resolve(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(origin.read_bytes())
            break

    for relative, owner in owner_of.items():
        source = workspaces.get(owner)
        if source is None or not source.contains(relative):
            continue
        origin = source.resolve(relative)
        if not origin.is_file():
            continue
        target = merged.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(origin.read_bytes())

    return merged, merge_conflicts


def _merge_contested(
    relative: str, workspaces: dict[str, Workspace], base_root: Path, merged: Workspace
) -> bool:
    """Three-way merge one contested path into `merged`; False if it conflicted.

    Only agents whose file differs from the fixture's take part, so an agent the
    C3 gate blocked (its file never changed) cannot win or lose anything. One
    changed side is taken as it is. A file one agent deleted and another edited
    is a conflict, and so is a file both added differently (empty base).
    """
    base_file = base_root / relative
    base = base_file.read_bytes() if base_file.is_file() else None

    changed: dict[str, bytes | None] = {}
    for agent_id in sorted(workspaces):
        workspace = workspaces[agent_id]
        origin = workspace.resolve(relative) if workspace.contains(relative) else None
        content = origin.read_bytes() if origin is not None and origin.is_file() else None
        if content != base:
            changed[agent_id] = content

    def write(content: bytes) -> None:
        target = merged.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    if not changed:
        if base is not None:
            write(base)
        return True
    if len(changed) == 1:
        (only,) = changed.values()
        if only is not None:
            write(only)
        return True

    contents = list(changed.items())
    if any(content is None for _, content in contents):
        # Deleted on one side, changed on the other. Keep a surviving side's file so the
        # integrated workspace still has something to run, and report the conflict.
        survivors = [content for _, content in contents if content is not None]
        if survivors:
            write(survivors[0])
        return all(content is None for _, content in contents)

    label, accumulated = contents[0]
    assert accumulated is not None
    clean = True
    for agent_id, content in contents[1:]:
        assert content is not None
        result = merge_three_way(
            base or b"", accumulated, content, ours_label=label, theirs_label=agent_id
        )
        accumulated = result.content
        label = f"{label}+{agent_id}"
        clean = clean and result.clean
    write(accumulated)
    return clean


def _last_writer(path: str, records: list[dict[str, Any]]) -> str | None:
    """Which agent last successfully wrote this path, per the signed chain.

    Only mutating events count, and only ones the relay accepted: a write
    the C3 gate refused never becomes an event, so a blocked agent cannot
    win a contested path. Returns None when nobody wrote it, leaving the
    caller to fall back to whatever the fixture provided.
    """
    mutating = {"write", "create", "modify", "rename", "delete"}
    winner: str | None = None
    best = -1
    for record in records:
        event = record.get("event", {})
        if str(event.get("event_type", "")).lower() not in mutating:
            continue
        if path not in event.get("paths", ()):
            continue
        sequence = event.get("sequence", -1)
        if sequence >= best:
            best = sequence
            winner = event.get("identity", {}).get("agent_id")
    return winner


def _harness_environment() -> dict[str, str]:
    """The scrubbed environment the integration test runs under.

    One definition, used by the test itself and by its preflight, so the
    preflight asks the question of the interpreter the test will really get.
    """
    return {
        **{name: os.environ[name] for name in _INHERITED_ENVIRONMENT if name in os.environ},
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


@functools.cache
def resolve_executable(name: str, path: str | None = None) -> str | None:
    """`shutil.which`, except that on Windows a `bash` that cannot run is no answer.

    A shell whose `PATH` carries only `Git\\cmd` finds the WSL relay at
    System32 first. With no distro it exits 1 ("execvpe(/bin/bash) failed"),
    the same code as a failed test, so every arm would fail identically and
    nothing would say why. A `bash` that does not run is therefore skipped, and
    the one beside `git` (Git for Windows: `<root>\\bin\\bash.exe`) is tried.
    Returns `None` when no working `bash` exists, so the preflight can say so.
    """
    import shutil
    import subprocess
    import sys

    found = shutil.which(name, path=path)
    if name != "bash" or sys.platform != "win32":
        return found
    git = shutil.which("git", path=path)
    candidates = [found] if found else []
    if git:
        for root in Path(git).parents[1:3]:
            candidates += [str(root / "bin" / "bash.exe"), str(root / "usr" / "bin" / "bash.exe")]
    for candidate in candidates:
        try:
            ran = subprocess.run(
                [candidate, "-c", "exit 0"], capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if ran.returncode == 0:
            return candidate
    return None


def integration_test_preflight(task: TaskDefinition) -> str | None:
    """Why this task's integration test cannot run here, or `None` if it can.

    Without this a missing test runner is indistinguishable from a task that
    does not discriminate between arms. `python -m pytest` with no pytest
    installed exits 1, the same code as "a test failed", so every arm fails
    identically and the sec 37 gate reports NOT SENSITIVE for a reason that has
    nothing to do with the task (it happened to `interface_consumer` and
    `shared_utility_refactor`). Checked against the harness's own environment,
    not this process's: the test runs under a scrubbed one, and the `python` on
    its `PATH` need not be the one running the harness.

    Two things are checked: the command's executable resolves, and, for the
    `<python> -m <module>` form every shipped task uses, that the module is
    importable by that interpreter. Any other command shape is not probed and
    is assumed runnable; the check says what it knows, not more.
    """
    import subprocess
    import tempfile

    argv = list(task.success.integration_test)
    if not argv:
        return None
    env = _harness_environment()
    executable = resolve_executable(argv[0], env.get("PATH"))
    if executable is None:
        return (
            f"{argv[0]!r} is not found on the harness's PATH (or is a stub that cannot run), "
            "so the integration test cannot run"
        )
    if len(argv) < 3 or argv[1] != "-m":
        return None
    module = argv[2]
    probe = (
        "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 3)"
    )
    try:
        with tempfile.TemporaryDirectory() as scratch:
            completed = subprocess.run(
                [executable, "-c", probe, module],
                cwd=scratch,
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not start {executable!r} to check for module {module!r}: {exc}"
    if completed.returncode == 0:
        return None
    return (
        f"the interpreter the harness will use ({executable}) cannot import {module!r}; "
        f"the integration test would fail in every arm for that reason alone"
    )


def _run_integration_test(task: TaskDefinition, workspace: Workspace) -> int | None:
    """Run the task's integration test in a workspace.

    Run by the harness rather than by an agent: §38 requires success to be
    decided automatically, and an agent-run test could report whatever it
    liked. Deliberately outside the tool boundary — this is the
    experimenter measuring the result, not the agent acting.
    """
    import subprocess

    env = _harness_environment()
    argv = list(task.success.integration_test)
    # Resolve the executable on the harness's own PATH. On Windows CreateProcess
    # looks in System32 before PATH, so a bare `bash` runs WSL's relay (which
    # exits 1 with no distro) instead of the Git Bash the preflight just found,
    # and every arm fails identically.
    if argv and (resolved := resolve_executable(argv[0], env.get("PATH"))):
        argv[0] = resolved
    try:
        completed = subprocess.run(
            argv,
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.returncode
