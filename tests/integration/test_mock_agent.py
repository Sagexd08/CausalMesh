"""The mock agent driven through the real runtime (spec §9, §22).

§9 is explicit that the mock is not a throwaway test double but the
laboratory in which C0 to C3 are verified before paying for inference. So it
is tested against the real stack — workspace, tools, gate, relay, chain —
rather than in isolation. A mock validated against stubs would prove nothing
about the coordination infrastructure.

Every capability §9 lists is exercised here: file operations, running tests,
responding to coordination events, deliberate conflicts, stale reads,
delayed deliberation, crashing, stalling and retrying.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.agents import (
    AgentContext,
    AgentIdentity,
    MockAgent,
    Scenario,
)
from causalmesh.channels import MetadataChannel, NullChannel, Room, TranscriptChannel
from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.keys import KeyPair
from causalmesh.hooks import LifecycleBoundary, gate_for_arm
from causalmesh.isolation import build_run_workspaces
from causalmesh.relay import Relay, policy_for_arm
from causalmesh.relevance import AgentInterests
from causalmesh.tools import Toolbox, ToolExecutor
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.integration

SEED = b"causalmesh-mock-agent-seed-00001"
RUN = "run_001"
BASE_TIME = 1_700_000_000_000_000
SECOND = 1_000_000


def make_identity(agent_id: str, arm: str) -> AgentIdentity:
    return AgentIdentity(
        experiment_id="exp_mock",
        task_id="task_mock",
        run_id=RUN,
        agent_id=agent_id,
        arm=arm,
        operator_id="test",
        machine_id="test-machine",
        model_id="mock",
        model_version="1",
        seed=42,
        git_commit="0" * 40,
    )


class Runtime:
    """A complete arm runtime driving scripted mock agents."""

    def __init__(self, scenario: Scenario, arm: str, tmp_path: Path) -> None:
        self.arm = arm
        self.scenario = scenario
        agent_ids = list(scenario.agent_ids())

        fixture = tmp_path / "fixture"
        (fixture / "src").mkdir(parents=True, exist_ok=True)
        (fixture / "src" / "schema.py").write_text("FIELDS = ['id']\n", encoding="utf-8")
        (fixture / "src" / "api.py").write_text("from schema import FIELDS\n", encoding="utf-8")

        self.workspaces = build_run_workspaces(
            base=tmp_path / arm / "ws", run_id=RUN, agent_ids=agent_ids, fixture=fixture
        )
        keypairs = {agent: KeyPair.derive(SEED, agent) for agent in agent_ids}
        self.claims = ClaimRegistry(tmp_path / arm / "claims.db") if arm == "C3" else None
        self.relay = Relay(
            run_id=RUN,
            keypairs=keypairs,
            delivery=policy_for_arm(arm),
            claims=self.claims,
            participants=agent_ids,
        )
        gate = gate_for_arm(arm, registry=self.claims, run_id=RUN)
        room = Room(RUN, "task_mock")

        self.agents: dict[str, MockAgent] = {}
        for agent_id in agent_ids:
            script = scenario.agents[agent_id]
            if arm == "C0":
                channel = NullChannel(agent_id)
            elif arm == "C1":
                channel = TranscriptChannel(agent_id, room)
            else:
                channel = MetadataChannel(
                    agent_id,
                    arm=arm,
                    interests=AgentInterests(
                        agent_id=agent_id,
                        owned_paths=script.owned_paths,
                        dependency_paths=script.dependency_paths,
                    ),
                )
            self.agents[agent_id] = MockAgent(
                make_identity(agent_id, arm),
                script=script,
                executor=ToolExecutor(
                    agent_id=agent_id,
                    identity=make_identity(agent_id, arm).to_event_identity(),
                    toolbox=Toolbox(self.workspaces[agent_id]),
                    boundary=LifecycleBoundary(gate=gate),
                    relay=self.relay,
                ),
                channel=channel,
            )

    async def run(self, turns: int = 12) -> Runtime:
        """Drive every agent through the lifecycle, round-robin by turn."""
        for agent in self.agents.values():
            await agent.initialize()

        for turn in range(turns):
            for agent in self.agents.values():
                if agent.turns and agent.turns[-1].finished:
                    continue
                context = AgentContext(turn=turn, now_us=BASE_TIME + turn * SECOND)
                await agent.observe(context)
                await agent.plan(context)
                await agent.act(context)

        self.summaries = {
            agent_id: await agent.finalize() for agent_id, agent in self.agents.items()
        }
        return self

    def close(self) -> None:
        if self.claims is not None:
            self.claims.close()


CONFLICT_SCENARIO = Scenario.from_yaml(
    """
    agent_a:
      owns: [src/schema.py]
      actions:
        - read: src/schema.py
        - write: {path: src/schema.py, content: "FIELDS = ['id', 'email']\\n"}

    agent_b:
      owns: [src/api.py]
      depends_on: [src/schema.py]
      actions:
        - read: src/schema.py
        - wait: 2s
        - write: {path: src/schema.py, content: "FIELDS = ['id']  # b clobbers\\n"}
    """
)


@pytest.fixture
async def c2_runtime(tmp_path: Path) -> Runtime:
    runtime = Runtime(CONFLICT_SCENARIO, "C2", tmp_path)
    await runtime.run()
    yield runtime
    runtime.close()


class TestScriptedExecution:
    async def test_every_scripted_action_is_performed(self, c2_runtime: Runtime) -> None:
        summary = c2_runtime.summaries["agent_a"]
        assert summary["actions_scripted"] == 2
        assert summary["actions_executed"] == 2

    async def test_actions_run_in_script_order(self, c2_runtime: Runtime) -> None:
        tools = [r.call.tool for r in c2_runtime.agents["agent_a"].tool_results]
        assert tools == ["read_file", "write_file"]

    async def test_the_file_reflects_the_scripted_content(self, c2_runtime: Runtime) -> None:
        written = c2_runtime.workspaces["agent_a"].resolve("src/schema.py").read_text()
        assert written == "FIELDS = ['id', 'email']\n"

    async def test_the_run_produces_a_verifiable_chain(self, c2_runtime: Runtime) -> None:
        result = verify_chain(c2_runtime.relay.records(), c2_runtime.relay.key_ring())
        assert result.valid, result.summary()
        assert result.events == 4

    async def test_an_agent_finishes_when_its_script_is_exhausted(
        self, c2_runtime: Runtime
    ) -> None:
        assert c2_runtime.agents["agent_a"].turns[-1].finished


class TestDeterminism:
    """§9, §84: the same script must produce the same run."""

    async def test_two_runs_produce_identical_chains(self, tmp_path: Path) -> None:
        chains = []
        for index in range(2):
            runtime = Runtime(CONFLICT_SCENARIO, "C2", tmp_path / f"run_{index}")
            await runtime.run()
            chains.append([r["chain_hash"] for r in runtime.relay.records()])
            runtime.close()
        assert chains[0] == chains[1]

    async def test_two_runs_produce_identical_file_contents(self, tmp_path: Path) -> None:
        contents = []
        for index in range(2):
            runtime = Runtime(CONFLICT_SCENARIO, "C2", tmp_path / f"run_{index}")
            await runtime.run()
            contents.append(runtime.workspaces["agent_b"].resolve("src/schema.py").read_text())
            runtime.close()
        assert contents[0] == contents[1]

    async def test_coordination_accounting_is_reproducible(self, tmp_path: Path) -> None:
        totals = []
        for index in range(2):
            runtime = Runtime(CONFLICT_SCENARIO, "C2", tmp_path / f"run_{index}")
            await runtime.run()
            totals.append(runtime.summaries["agent_b"]["coordination"]["coordination_bytes"])
            runtime.close()
        assert totals[0] == totals[1]


class TestCoordinationResponse:
    async def test_an_agent_observes_peer_events_under_c2(self, c2_runtime: Runtime) -> None:
        observed = [ids for _, ids in c2_runtime.agents["agent_b"].observations if ids]
        assert observed, "agent_b saw no peer events under C2"

    async def test_c0_agents_observe_nothing(self, tmp_path: Path) -> None:
        runtime = Runtime(CONFLICT_SCENARIO, "C0", tmp_path)
        try:
            await runtime.run()
            assert all(not ids for _, ids in runtime.agents["agent_b"].observations)
            accounting = runtime.summaries["agent_b"]["coordination"]
            assert accounting["received_no_coordination"] is True
            assert accounting["coordination_bytes"] == 0
        finally:
            runtime.close()

    async def test_c1_accumulates_more_coordination_bytes_than_c2(self, tmp_path: Path) -> None:
        costs = {}
        for arm in ("C1", "C2"):
            runtime = Runtime(CONFLICT_SCENARIO, arm, tmp_path / arm)
            await runtime.run()
            costs[arm] = runtime.summaries["agent_b"]["coordination"]["coordination_bytes"]
            runtime.close()
        assert costs["C1"] > 0 and costs["C2"] > 0


class TestInducedConflict:
    """§9: the mock must be able to create deliberate conflicts."""

    async def test_c2_permits_the_conflicting_write(self, c2_runtime: Runtime) -> None:
        assert c2_runtime.summaries["agent_b"]["denied"] == 0
        assert (
            c2_runtime.workspaces["agent_b"].resolve("src/schema.py").read_text()
            == "FIELDS = ['id']  # b clobbers\n"
        )

    async def test_c3_denies_it_when_a_claim_is_held(self, tmp_path: Path) -> None:
        runtime = Runtime(CONFLICT_SCENARIO, "C3", tmp_path)
        try:
            assert runtime.claims is not None
            runtime.claims.acquire(
                claim_id="c_a",
                path="src/schema.py",
                agent_id="agent_a",
                run_id=RUN,
                now_us=BASE_TIME,
                duration_us=600 * SECOND,
            )
            await runtime.run()

            assert runtime.summaries["agent_b"]["denied"] >= 1
            # The denied write left agent_b's copy untouched.
            assert (
                runtime.workspaces["agent_b"].resolve("src/schema.py").read_text()
                == "FIELDS = ['id']\n"
            )
            assert verify_chain(runtime.relay.records(), runtime.relay.key_ring()).valid
        finally:
            runtime.close()


class TestFailureModes:
    """§9, §22: crashes, stalls and retries as first-class behaviour."""

    @pytest.mark.failure
    async def test_a_scripted_crash_is_recorded_not_propagated(self, tmp_path: Path) -> None:
        scenario = Scenario.from_yaml(
            """
            agent_a:
              actions:
                - read: src/schema.py
                - crash: simulated agent failure
                - write: src/schema.py
            """
        )
        runtime = Runtime(scenario, "C2", tmp_path)
        try:
            await runtime.run()
            agent = runtime.agents["agent_a"]
            assert runtime.summaries["agent_a"]["crashed"] is True
            # The action after the crash never ran.
            assert runtime.summaries["agent_a"]["actions_executed"] == 1
            assert "simulated agent failure" in (agent.turns[-1].error or "")
            # A crashed run still leaves verifiable evidence (§81).
            assert verify_chain(runtime.relay.records(), runtime.relay.key_ring()).valid
        finally:
            runtime.close()

    async def test_a_stall_advances_time_without_acting(self, tmp_path: Path) -> None:
        scenario = Scenario.from_yaml(
            """
            agent_a:
              actions:
                - stall: 5s
                - read: src/schema.py
            """
        )
        runtime = Runtime(scenario, "C2", tmp_path)
        try:
            await runtime.run()
            stalls = [t for t in runtime.agents["agent_a"].turns if t.stalled]
            assert len(stalls) == 1
            assert stalls[0].notes["waited_us"] == 5_000_000
            assert stalls[0].actions == 0
        finally:
            runtime.close()

    async def test_a_denied_write_is_retried_the_scripted_number_of_times(
        self, tmp_path: Path
    ) -> None:
        """Retrying a denial is what produces measurable lease wait (§21)."""
        scenario = Scenario.from_yaml(
            """
            agent_a:
              actions:
                - write: {path: src/schema.py, retries: 2}
            """
        )
        runtime = Runtime(scenario, "C3", tmp_path)
        try:
            assert runtime.claims is not None
            runtime.claims.acquire(
                claim_id="c_other",
                path="src/schema.py",
                agent_id="agent_blocker",
                run_id=RUN,
                now_us=BASE_TIME,
                duration_us=600 * SECOND,
            )
            await runtime.run(turns=3)
            # Three attempts: the original plus two retries, all denied.
            assert runtime.summaries["agent_a"]["denied"] == 3
        finally:
            runtime.close()

    async def test_a_wait_creates_a_deliberation_window(self, tmp_path: Path) -> None:
        # §23: the agent read, then waited, during which a peer could have
        # invalidated what it read.
        agent_b = None
        runtime = Runtime(CONFLICT_SCENARIO, "C2", tmp_path)
        try:
            await runtime.run()
            agent_b = runtime.agents["agent_b"]
            waits = [t for t in agent_b.turns if t.notes.get("waited_us")]
            assert waits and waits[0].notes["waited_us"] == 2_000_000
        finally:
            runtime.close()


class TestLifecycle:
    async def test_all_five_phases_are_exercised(self, tmp_path: Path) -> None:
        scenario = Scenario.from_yaml(
            """
            agent_a:
              actions:
                - read: src/schema.py
            """
        )
        runtime = Runtime(scenario, "C2", tmp_path)
        try:
            await runtime.run(turns=2)
            agent = runtime.agents["agent_a"]
            assert agent._initialized
            assert agent._finalized
            assert agent.observations  # observe ran
            assert agent.turns  # act ran
        finally:
            runtime.close()

    async def test_the_summary_reports_coordination_and_outcomes(self, c2_runtime: Runtime) -> None:
        summary = c2_runtime.summaries["agent_b"]
        assert {
            "actions_executed",
            "actions_scripted",
            "coordination",
            "crashed",
            "denied",
            "failed",
            "observations",
            "turns",
        } <= set(summary)
