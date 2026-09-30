"""Running the scalability profile (spec §86).

For each cell of the profile (agent count, arm, delivery mode, topology) this
generates the scaled task, materialises its fixture in a scratch directory,
runs it through `execute_task` with the scripted mock agents, verifies the
chain offline, and reads the coordination costs out of the result.

Nothing here measures cost itself. Bytes and delivered-event counts are what
the channels recorded at injection time; the only quantity derived here is
`events_available`, the broadcast counterfactual, which is a function of the
chain (events by agents times N-1) and is labelled as such.

Everything reported is a property of scripted mock agents running one
generated task on the machine that ran it. It says how the delivery layer's
cost grows under that topology, not how real agents would coordinate.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..crypto.keys import KeyPair, PublicKeyRing
from ..experiments.scalability import DENSE, ScalabilityProfile
from ..metrics.scaling import ScalingRun, ScalingSeries, summarize_scaling
from ..verifier import verify_chain
from .runner import RunConfig, RunResult, execute_task
from .scaled import ScaledSpec, generate_scaled_task, write_scaled_fixture

__all__ = [
    "ScalabilityReport",
    "measure_run",
    "render_scalability",
    "run_scalability",
    "spec_for",
]


def spec_for(profile: ScalabilityProfile, *, n_agents: int, topology: str) -> ScaledSpec:
    """The task spec for one cell: `dense` puts every agent in one group."""
    group_size = n_agents if topology == DENSE else min(profile.group_size, n_agents)
    return ScaledSpec(n_agents=n_agents, group_size=group_size, own_files=profile.own_files)


def measure_run(
    result: RunResult,
    *,
    spec: ScaledSpec,
    topology: str,
    delivery_mode: str,
    master_seed: bytes,
) -> ScalingRun:
    """Read one run's delivery and coordination costs out of its result.

    The chain is verified here, offline, against keys re-derived from the
    seed: a cost reported from a run whose evidence does not verify would be
    a number without a record behind it.
    """
    agents = [spec.agent_id(i) for i in range(spec.n_agents)]
    ring = PublicKeyRing.from_keypairs(
        {actor: KeyPair.derive(master_seed, actor) for actor in [*agents, "acceptance"]}
    )
    chain_valid = verify_chain(result.records, ring).valid

    agent_set = set(agents)
    agent_events = sum(
        1 for record in result.records if record["event"]["identity"]["agent_id"] in agent_set
    )
    summaries = [result.agent_summaries[agent]["coordination"] for agent in agents]
    # Delivered events come from what each agent drained from its inbox, not
    # from the channel's `events_available`: the metadata channel re-counts
    # its carried-over backlog on every turn, so summing that counter would
    # report more deliveries than the relay made.
    delivered = tuple(
        sum(len(o["event_ids"]) for o in result.agent_summaries[agent]["observations"])
        for agent in agents
    )

    return ScalingRun(
        n_agents=spec.n_agents,
        arm=result.arm,
        delivery_mode=delivery_mode,
        topology=topology,
        group_size=spec.group_size,
        agent_events=agent_events,
        events_available=agent_events * (spec.n_agents - 1),
        events_delivered=sum(delivered),
        # The transcript channel's `events_injected` is replay volume (the
        # whole history every turn), not a count of distinct events, so it is
        # unknown for that arm rather than a number that means something else.
        events_injected=(
            None if result.arm == "C1" else sum(s["events_injected"] for s in summaries)
        ),
        coordination_bytes=sum(s["coordination_bytes"] for s in summaries),
        per_agent_bytes=tuple(s["coordination_bytes"] for s in summaries),
        per_agent_delivered=delivered,
        succeeded=result.outcome.succeeded if result.error is None else None,
        chain_valid=chain_valid,
        head_hash=result.head_hash,
    )


@dataclass
class ScalabilityReport:
    """Every run of a profile, and the curves they form."""

    profile: ScalabilityProfile
    seed: str
    runs: list[ScalingRun]

    @property
    def series(self) -> list[ScalingSeries]:
        return summarize_scaling(self.runs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "note": (
                "Measured on the machine that ran it, with scripted mock agents. "
                "Not evidence about real agent behaviour."
            ),
            "profile": self.profile.to_dict(),
            "runs": [run.to_dict() for run in self.runs],
            "seed": self.seed,
            "series": [series.to_dict() for series in self.series],
        }


async def run_scalability(
    profile: ScalabilityProfile,
    *,
    workspace_root: Path,
    seed: bytes = b"causalmesh-scalability-seed-0001",
    on_run: Callable[[ScalingRun], None] | None = None,
) -> ScalabilityReport:
    """Run every cell of `profile` and return the measurements.

    The same seed gives the same chain for the same cell (§84), so a repeat
    is a check on determinism and adds no statistical information: the mock
    agents have no randomness to average over. Hence no repetitions.
    """
    workspace_root = Path(workspace_root)
    fixtures_root = workspace_root / "fixtures"
    runs: list[ScalingRun] = []

    for topology in profile.topologies:
        for n_agents in profile.agent_counts:
            spec = spec_for(profile, n_agents=n_agents, topology=topology)
            task = generate_scaled_task(spec)
            write_scaled_fixture(spec, fixtures_root)
            for arm in profile.arms:
                for mode in profile.delivery_modes:
                    run_id = f"{spec.task_id}_{arm.lower()}_{mode}"
                    result = await execute_task(
                        task,
                        RunConfig(
                            experiment_id=f"scalability_{profile.name}",
                            run_id=run_id,
                            arm=arm,
                            master_seed=seed,
                            delivery_mode=mode,
                        ),
                        workspace_root=workspace_root / "runs",
                        fixtures_root=fixtures_root,
                    )
                    measured = measure_run(
                        result,
                        spec=spec,
                        topology=topology,
                        delivery_mode=mode,
                        master_seed=seed,
                    )
                    runs.append(measured)
                    if on_run is not None:
                        on_run(measured)
                    shutil.rmtree(workspace_root / "runs" / run_id, ignore_errors=True)

    return ScalabilityReport(profile=profile, seed=seed.decode("ascii", "replace"), runs=runs)


def _fmt(value: float | None, digits: int = 2) -> str:
    return "unknown" if value is None else f"{value:.{digits}f}"


def _count(value: int | None) -> str:
    return "unknown" if value is None else str(value)


def render_scalability(report: ScalabilityReport) -> str:
    """A plain ASCII table of the runs, then the fitted exponents."""
    header = (
        f"{'arm':<4} {'topology':<9} {'mode':<11} {'N':>3} {'available':>9} "
        f"{'delivered':>9} {'ratio':>6} {'unseen':>6} {'bytes':>9} {'bytes/agent':>11} {'ok':>4} {'chain':>5}"
    )
    lines = [header, "-" * len(header)]
    for series in report.series:
        for run in sorted(series.runs, key=lambda r: r.n_agents):
            ok = "unknown" if run.succeeded is None else ("yes" if run.succeeded else "no")
            lines.append(
                f"{run.arm:<4} {run.topology:<9} {run.delivery_mode:<11} {run.n_agents:>3} "
                f"{run.events_available:>9} {run.events_delivered:>9} "
                f"{_fmt(run.delivery_ratio):>6} {_count(run.events_unseen):>6} "
                f"{run.coordination_bytes:>9} "
                f"{_fmt(run.mean_bytes_per_agent, 1):>11} {ok:>4} "
                f"{'ok' if run.chain_valid else 'BAD':>5}"
            )
    lines.append("")
    lines.append("growth exponent of a cost against N (1 = linear, 2 = quadratic):")
    for series in report.series:
        lines.append(
            f"  {series.arm} {series.topology:<9} {series.delivery_mode:<11} "
            f"delivered {_fmt(series.exponent('events_delivered'))}  "
            f"bytes {_fmt(series.exponent('coordination_bytes'))}"
        )
    lines.append("")
    lines.append("Measured here with scripted mock agents; not evidence about real agents.")
    return "\n".join(lines)
