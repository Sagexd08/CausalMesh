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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents import AgentContext, AgentIdentity, MockAgent, Scenario
from ..channels import MetadataChannel, NullChannel, Room, TranscriptChannel
from ..channels.base import CoordinationChannel
from ..claims import ClaimRegistry
from ..crypto.keys import KeyPair
from ..events.schema import EventIdentity, EventType, utc_now_micros
from ..hooks import LifecycleBoundary, gate_for_arm
from ..isolation import Workspace, build_run_workspaces
from ..relay import ChainStore, Relay, policy_for_arm
from ..relevance import AgentInterests
from ..tools import Toolbox, ToolExecutor
from ..tools.api import _INHERITED_ENVIRONMENT
from .definition import TaskDefinition
from .outcome import TaskOutcome, evaluate_outcome, workspace_digest

__all__ = ["RunConfig", "RunResult", "execute_task"]

# Enough turns for the longest scripted agent plus a margin. Bounded so a
# stalled agent cannot hang a run indefinitely (§22).
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
    # A declared contract, when the operator has one. Absent is the
    # experiment's own case: the arms install `ClaimGate`, which refuses on
    # exactly one factor, and that is what the C2 to C3 contrast measures.
    # Present, the contract gate is installed instead and can also refuse on
    # ownership, allowlists, ceilings and budgets.
    #
    # A path rather than a Contract so RunConfig stays serialisable: it is
    # recorded in the run artifact, and an object with a Decimal in it is
    # not JSON.
    contract_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
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
    records: list[dict[str, Any]]
    head_hash: str | None
    agent_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    workspace_digests: dict[str, dict[str, str]] = field(default_factory=dict)
    claim_history: list[dict[str, Any]] = field(default_factory=list)
    denials: list[dict[str, Any]] = field(default_factory=list)
    relay_summary: dict[str, Any] = field(default_factory=dict)
    boundary_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)
    # What the contract gate decided, when one was installed. Empty for a
    # run driven by the arms' own gate, which is the experiment's default
    # and has no contract to report against.
    gate_summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome.succeeded

    def coordination_bytes(self) -> int:
        return sum(
            summary["coordination"]["coordination_bytes"]
            for summary in self.agent_summaries.values()
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_summaries": self.agent_summaries,
            "arm": self.arm,
            "boundary_summaries": self.boundary_summaries,
            "claim_history": self.claim_history,
            "coordination_bytes": self.coordination_bytes(),
            "denials": self.denials,
            "error": self.error,
            "events": len(self.records),
            "gate": self.gate_summary,
            "head_hash": self.head_hash,
            "outcome": self.outcome.to_dict(),
            "relay_summary": self.relay_summary,
            "run_id": self.run_id,
            "task_hash": self.task_hash,
            "task_id": self.task_id,
            "workspace_digests": self.workspace_digests,
        }


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


def _gate_for(config: RunConfig, *, registry: Any):
    """The gate this run installs, and why.

    Without a contract the arms install their own gate: `AllowAllGate` for
    C0, C1 and C2, `ClaimGate` for C3. That is the experiment's factor, and
    it stays the default because the C2 to C3 contrast is only clean if the
    two arms differ by exactly one thing.

    With a contract, `ContractGate` is installed instead. It can also refuse
    on ownership, allowlists, ceilings and budgets, and it keeps the arm's
    enforcement semantics: C3 enforces, the others reach a verdict and allow
    anyway so the counterfactual stays measurable.
    """
    if config.contract_path is None:
        return gate_for_arm(config.arm, registry=registry, run_id=config.run_id)

    from ..hooks.policy_gate import ContractGate
    from ..policy import Contract

    return ContractGate.build(
        Contract.load(config.contract_path),
        run_id=config.run_id,
        registry=registry,
        enforcing=config.arm == "C3",
    )


async def execute_task(
    task: TaskDefinition,
    config: RunConfig,
    *,
    workspace_root: Path,
    fixtures_root: Path,
    chain_path: Path | None = None,
) -> RunResult:
    """Run one task under one arm and return the result with its evidence.

    Follows the §79 loop: prepare isolated workspaces, initialize agents and
    the relay, run the task, collect coordination and claims, run the
    success check, and return everything.
    """
    scenario = Scenario.from_dict(task.scenario)
    agent_ids = list(task.agent_ids)

    workspaces = build_run_workspaces(
        base=workspace_root,
        run_id=config.run_id,
        agent_ids=agent_ids,
        fixture=Path(fixtures_root) / task.fixture,
    )

    keypairs = {agent: KeyPair.derive(config.master_seed, agent) for agent in agent_ids}
    # The policy plane is not an agent, but its verdicts still need a real
    # signing identity so they can enter the chain — see docs/backlog.md's
    # "Verdicts do not enter the signed chain" entry. Only derived when a
    # contract is in play; an experiment run with no contract has no
    # ContractGate and therefore no verdicts to sign.
    if config.contract_path is not None:
        keypairs["policy_gate"] = KeyPair.derive(config.master_seed, "policy_gate")
    claims = (
        ClaimRegistry(workspace_root / f"{config.run_id}_claims.db") if config.arm == "C3" else None
    )
    store = ChainStore(chain_path) if chain_path is not None else ChainStore()

    relay = Relay(
        run_id=config.run_id,
        keypairs=keypairs,
        store=store,
        delivery=policy_for_arm(config.arm),
        claims=claims,
        participants=agent_ids,
    )
    gate = _gate_for(config, registry=claims)
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

    # Under C3 each agent takes a lease on what it owns. This is the
    # enforcement the arm is defined by: an agent that owns a path holds it
    # for the run, so a peer's conflicting write is refused.
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
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        summaries = {agent_id: agent.summary() for agent_id, agent in agents.items()}

    # Success is judged on an *integrated* workspace, not on any single
    # agent's copy.
    #
    # Per-agent workspaces are an isolation mechanism (§11), not the
    # research model: the experiment is about agents coordinating over a
    # shared codebase that is later integrated. Judging one agent's copy
    # would ask the wrong question — it would score whether that agent's
    # local view is self-consistent, when what matters is whether the
    # agents' combined work is.
    #
    # Integration takes each file from the agent that owns it, which is
    # what an ownership-based merge does and what the claim registry
    # already encodes. A file nobody owns is taken from the fixture.
    integrated = _integrate_workspaces(
        task,
        workspaces,
        destination=workspace_root / f"{config.run_id}_integrated",
        records=relay.records(),
    )
    exit_code = _run_integration_test(task, integrated)
    outcome = evaluate_outcome(task.success, workspace=integrated, test_exit_code=exit_code)

    # Every verdict the policy gate reached becomes a real chain event —
    # not only refusals, so an unenforced arm's shadow-refusals (the
    # counterfactual §-referenced throughout policy_gate.py) are provable
    # too. `hasattr` rather than isinstance: the arms' own gates
    # (AllowAllGate, ClaimGate) have no `.verdicts` list to read, and that
    # absence is the honest signal that no contract was in play.
    if hasattr(gate, "verdicts"):
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
                timestamp_us=utc_now_micros(),
                payload=verdict.to_dict(),
            )
            if not ingested.accepted:
                # A verdict that cannot be recorded is exactly the silent
                # gap this change exists to close — fail loudly rather
                # than returning a result that looks complete but is
                # missing evidence.
                raise RuntimeError(
                    f"policy verdict {index} could not be recorded on the "
                    f"chain: {ingested.reason}"
                )

    result = RunResult(
        run_id=config.run_id,
        arm=config.arm,
        task_id=task.task_id,
        task_hash=task.content_hash(),
        outcome=outcome,
        records=relay.records(),
        head_hash=relay.head_hash,
        agent_summaries=summaries,
        workspace_digests={
            agent_id: workspace_digest(workspace) for agent_id, workspace in workspaces.items()
        },
        claim_history=[c.to_dict() for c in claims.history(run_id=config.run_id)] if claims else [],
        denials=claims.denials(run_id=config.run_id) if claims else [],
        # `to_dict` only exists on the contract gate. The arms' gates have
        # no contract to report against, so an absent summary is the honest
        # answer rather than an empty one that implies a gate was consulted.
        gate_summary=gate.to_dict() if hasattr(gate, "to_dict") else {},
        relay_summary=relay.summary(),
        boundary_summaries={
            agent_id: boundary.summary() for agent_id, boundary in boundaries.items()
        },
        error=error,
    )

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
) -> Workspace:
    """Merge the agents' workspaces into the shared codebase they represent.

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

    # A contested path has no single owner, by definition. Resolving it by
    # ownership would decide the contest before the arms could differ:
    # agent_b's write would be discarded in every arm, informed or not, and
    # the task would measure nothing.
    #
    # So contested paths are excluded from the ownership rule and merged
    # last-writer-wins instead — which is exactly what an unsynchronised
    # shared filesystem does, and therefore the behaviour the enforcement
    # factor exists to change.
    contested = set(task.contested_paths)
    for path in contested:
        owner_of.pop(path, None)

    # Lay down every agent's files first, then let owners overwrite. The
    # two passes matter: an owner's version must win regardless of the
    # order agents happen to be iterated in.
    for agent_id in sorted(workspaces):
        workspace = workspaces[agent_id]
        for relative in workspace.list_files():
            if relative in owner_of or relative in contested:
                continue
            target = merged.resolve(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(workspace.resolve(relative).read_bytes())

    # Contested paths are resolved from the *chain*, which is the only
    # authoritative record of who wrote what and in what order.
    #
    # The first version of this took the alphabetically last agent's copy
    # and called it last-writer-wins. It is not: under C3, agent_b's write
    # to the contested file was refused, so its workspace still held the
    # untouched fixture — and that empty copy overwrote agent_a's
    # successful write purely because "agent_b" sorts after "agent_a".
    # C3 then looked like it had lost both registrations when it had
    # actually preserved one. Filesystem mtimes would be no better: they
    # have coarse resolution and record when a file was touched, not which
    # write the system accepted.
    #
    # The relay assigns a monotonic sequence to every accepted event, and a
    # denied write produces no write event at all. Reading the order from
    # there means the merge agrees with the signed evidence by
    # construction.
    for relative in sorted(contested):
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

    return merged


def _last_writer(path: str, records: list[dict[str, Any]]) -> str | None:
    """Which agent last successfully wrote this path, per the signed chain.

    Only mutating events count, and only ones the relay accepted: a write
    the C3 gate refused never becomes an event, so a blocked agent cannot
    win a contested path. Returns None when nobody wrote it, leaving the
    caller to fall back to whatever the fixture provided.
    """
    # Compared case-insensitively against the event vocabulary: the chain
    # serialises these as "WRITE", and a lowercase comparison silently
    # matched nothing — every contested path then fell back to the fixture
    # and all four arms failed identically, which looks like a broken task
    # rather than a broken lookup.
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


def _run_integration_test(task: TaskDefinition, workspace: Workspace) -> int | None:
    """Run the task's integration test in a workspace.

    Run by the harness rather than by an agent: §38 requires success to be
    decided automatically, and an agent-run test could report whatever it
    liked. Deliberately outside the tool boundary — this is the
    experimenter measuring the result, not the agent acting.
    """
    import subprocess

    try:
        completed = subprocess.run(
            list(task.success.integration_test),
            cwd=workspace.root,
            capture_output=True,
            text=True,
            timeout=300,
            env={
                # Same allowlist the tool layer uses, for the same reasons —
                # including APPDATA, without which `python -m pytest` cannot
                # find user-site packages on Windows and every task's
                # integration test fails identically in every arm.
                **{name: os.environ[name] for name in _INHERITED_ENVIRONMENT if name in os.environ},
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        # A test that could not run is not a pass. Returning None keeps
        # "never ran" distinguishable from "ran and failed" in the evidence.
        return None
    return completed.returncode
