"""Model adapters driving the real substrate over real HTTP (spec §8, §71).

Every test here runs a genuine HTTP request over a socket to a server that
implements the chat-completions protocol, then drives the actual tool
boundary, gate, relay and chain with the reply.

The point of Phase 1's acceptance criterion: **every coordination
guarantee must hold identically with a model driving.** If a guarantee only
holds for the scripted agent, the substrate was coupled to determinism
rather than merely tested with it — and the guarantee was never real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.adapters import (
    AnthropicClient,
    LocalClient,
    ModelAgent,
    ModelSettings,
    OpenAIClient,
)
from causalmesh.agents import AgentContext, AgentIdentity
from causalmesh.channels import MetadataChannel, NullChannel, Room, TranscriptChannel
from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.keys import KeyPair, PublicKeyRing
from causalmesh.hooks import LifecycleBoundary, gate_for_arm
from causalmesh.isolation import build_run_workspaces
from causalmesh.relay import ChainStore, Relay, policy_for_arm
from causalmesh.relevance import AgentInterests
from causalmesh.tools import Toolbox, ToolExecutor
from causalmesh.verifier import verify_chain
from fake_model_server import FakeModelServer

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-model-adapter-testseed"


def identity_for(agent_id: str, arm: str) -> AgentIdentity:
    return AgentIdentity(
        experiment_id="exp_model",
        task_id="schema_handler_widen",
        run_id="run_model",
        agent_id=agent_id,
        arm=arm,
        operator_id="test",
        machine_id="test",
        model_id="fake-model",
        model_version="1",
        seed=1,
        git_commit="test",
    )


class Harness:
    """One assembled runtime, built exactly as `tasks.runner` builds it."""

    def __init__(self, tmp_path: Path, server: FakeModelServer, arm: str, client_kind: str):
        self.arm = arm
        self.agent_ids = ["agent_a", "agent_b"]
        self.workspaces = build_run_workspaces(
            base=tmp_path,
            run_id="run_model",
            agent_ids=self.agent_ids,
            fixture=FIXTURES / "schema_handler",
        )
        keypairs = {a: KeyPair.derive(SEED, a) for a in self.agent_ids}
        self.claims = ClaimRegistry(tmp_path / "claims.db") if arm == "C3" else None
        self.store = ChainStore()
        self.relay = Relay(
            run_id="run_model",
            keypairs=keypairs,
            store=self.store,
            delivery=policy_for_arm(arm),
            claims=self.claims,
            participants=self.agent_ids,
        )
        gate = gate_for_arm(arm, registry=self.claims, run_id="run_model")
        room = Room("run_model", "schema_handler_widen")

        settings = ModelSettings(model="fake-model")
        client = {
            "openai": lambda: OpenAIClient(api_key="test-key", base_url=server.base_url),
            "anthropic": lambda: AnthropicClient(api_key="test-key", base_url=server.base_url),
            "local": lambda: LocalClient(base_url=server.base_url),
        }[client_kind]()

        self.agents: dict[str, ModelAgent] = {}
        for agent_id in self.agent_ids:
            identity = identity_for(agent_id, arm)
            boundary = LifecycleBoundary(gate=gate)
            channel = (
                NullChannel(agent_id)
                if arm == "C0"
                else TranscriptChannel(agent_id, room)
                if arm == "C1"
                else MetadataChannel(
                    agent_id,
                    arm=arm,
                    window=8,
                    interests=AgentInterests(
                        agent_id=agent_id,
                        owned_paths=frozenset({f"src/{agent_id}.py"}),
                        dependency_paths=frozenset(),
                    ),
                )
            )
            self.agents[agent_id] = ModelAgent(
                identity,
                client=client,
                settings=settings,
                executor=ToolExecutor(
                    agent_id=agent_id,
                    identity=identity.to_event_identity(),
                    toolbox=Toolbox(self.workspaces[agent_id]),
                    boundary=boundary,
                    relay=self.relay,
                ),
                channel=channel,
                role_description="Test role",
                owns=("src/schema.py",) if agent_id == "agent_a" else ("src/handler.py",),
            )

    async def run(self, turns: int = 4) -> None:
        for agent in self.agents.values():
            await agent.initialize()
        for turn in range(turns):
            for agent in self.agents.values():
                context = AgentContext(turn=turn, now_us=1_700_000_000_000_000 + turn * 1_000_000)
                await agent.observe(context)
                await agent.plan(context)
                await agent.act(context)

    def close(self) -> None:
        self.store.close()
        if self.claims:
            self.claims.close()

    def key_ring(self) -> PublicKeyRing:
        return PublicKeyRing.from_keypairs({a: KeyPair.derive(SEED, a) for a in self.agent_ids})


class TestEveryProviderSpeaksItsProtocol:
    """Real requests over a socket, one test per provider."""

    @pytest.mark.parametrize("kind", ["openai", "anthropic", "local"])
    async def test_a_model_reply_becomes_a_recorded_tool_call(
        self, tmp_path: Path, kind: str
    ) -> None:
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="read_file", arguments={"path": "src/schema.py"})
            harness = Harness(tmp_path, server, "C2", kind)
            try:
                await harness.run(turns=1)
                records = harness.relay.records()
                reads = [r for r in records if r["event"]["event_type"].lower() == "read"]
                assert reads, f"{kind}: no read event was recorded"
                assert reads[0]["event"]["identity"]["agent_id"] == "agent_a"
            finally:
                harness.close()

    async def test_anthropic_hoists_the_system_prompt(self, tmp_path: Path) -> None:
        """Anthropic rejects role:system inside messages.

        A mocked transport would accept the wrong shape happily. Sending
        the system prompt in the message list would either fail the request
        or — on a lenient proxy — silently drop the agent's entire
        instruction set, which looks like a badly behaved model.
        """
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "anthropic")
            try:
                await harness.run(turns=1)
                request = server.requests[0]["body"]
                assert "system" in request, "system prompt was not hoisted"
                assert "You are agent_a," in request["system"]
                roles = {m["role"] for m in request["messages"]}
                assert "system" not in roles
            finally:
                harness.close()

    async def test_openai_keeps_the_system_prompt_in_messages(self, tmp_path: Path) -> None:
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "openai")
            try:
                await harness.run(turns=1)
                request = server.requests[0]["body"]
                assert "system" not in request
                assert request["messages"][0]["role"] == "system"
            finally:
                harness.close()

    async def test_the_api_key_reaches_the_right_header(self, tmp_path: Path) -> None:
        # OpenAI uses Authorization: Bearer, Anthropic uses x-api-key.
        # Sending the wrong one authenticates against neither.
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "anthropic")
            try:
                await harness.run(turns=1)
                # Header names are case-insensitive (RFC 9110) and urllib
                # title-cases them on the wire, so the lookup must be too.
                headers = {k.lower(): v for k, v in server.requests[0]["headers"].items()}
                assert headers.get("x-api-key") == "test-key"
                assert headers.get("anthropic-version") == "2023-06-01"
                # And the OpenAI-style header must NOT be sent: Anthropic
                # would ignore it and the request would be unauthenticated.
                assert "authorization" not in headers
            finally:
                harness.close()


class TestGuaranteesHoldWithAModelDriving:
    """Phase 1's acceptance criterion, guarantee by guarantee."""

    async def test_the_chain_verifies(self, tmp_path: Path) -> None:
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="read_file", arguments={"path": "src/schema.py"})
            server.queue_action(
                "agent_a",
                tool="write_file",
                arguments={"path": "src/schema.py", "content": "FIELDS = ['id']\n"},
            )
            server.queue_action("agent_b", tool="read_file", arguments={"path": "src/handler.py"})
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=2)
                report = verify_chain(harness.relay.records(), harness.key_ring())
                assert report.valid, report.summary()
            finally:
                harness.close()

    async def test_attribution_survives(self, tmp_path: Path) -> None:
        # Every event must name the agent that caused it, with a signature
        # that verifies against that agent's key.
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            server.queue_action("agent_b", tool="git_diff", arguments={})
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=1)
                actors = {r["event"]["identity"]["agent_id"] for r in harness.relay.records()}
                assert actors == {"agent_a", "agent_b"}
                assert verify_chain(harness.relay.records(), harness.key_ring()).valid
            finally:
                harness.close()

    async def test_containment_holds_against_a_hostile_model(self, tmp_path: Path) -> None:
        """A model asking to escape its workspace must be refused.

        This is the containment guarantee under adversarial model output,
        which is the case that actually matters: the scripted agent never
        asks for anything it should not get.
        """
        with FakeModelServer() as server:
            server.queue_action(
                "agent_a",
                tool="read_file",
                arguments={"path": "../agent_b/src/handler.py"},
            )
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=1)
                results = harness.agents["agent_a"].tool_results
                assert results, "no tool call was attempted"
                assert results[0].outcome.value != "executed", (
                    "a peer-workspace read succeeded; containment is broken"
                )
                # And the attempt is recorded, not silently dropped.
                failures = [
                    r
                    for r in harness.relay.records()
                    if r["event"]["event_type"].lower() == "failure"
                ]
                assert failures
            finally:
                harness.close()

    async def test_c0_isolation_holds(self, tmp_path: Path) -> None:
        # The NullChannel raises if anything is offered, so a contaminated
        # C0 run fails rather than completing and looking valid.
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            server.queue_action("agent_b", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C0", "local")
            try:
                await harness.run(turns=2)
                for agent in harness.agents.values():
                    summary = agent.summary()
                    assert summary["coordination"]["coordination_bytes"] == 0
                    assert summary["informed_paths"] == []
            finally:
                harness.close()

    async def test_the_channel_is_the_only_route_information_takes(self, tmp_path: Path) -> None:
        """Nothing may reach the model's context except through the channel.

        This is the guarantee the whole experiment rests on: if peer
        information can enter by any other route, the coordination-byte
        accounting is not a complete account of what the agent knew, and
        the C0/C2 contrast measures something other than information.

        Added because a mutation that fed delivered events straight into
        the conversation — bypassing the channel entirely — passed every
        other test in this file. C0 stayed safe only because NullChannel
        raises; under C2 an agent would have received unaccounted
        information with nothing recording it.

        The check: every byte of peer content in the conversation must be
        accounted for in the channel's injected-byte total.
        """
        with FakeModelServer() as server:
            server.queue_action(
                "agent_a",
                tool="write_file",
                arguments={"path": "src/schema.py", "content": "FIELDS = ['id']\n"},
            )
            server.queue_action("agent_b", tool="git_status", arguments={})
            server.queue_action("agent_b", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=2)
                agent = harness.agents["agent_b"]
                accounted = agent.channel.accounting.to_dict()["coordination_bytes"]

                # Every message the agent did not author itself, minus the
                # harness's own turn prompts and its own system prompt.
                peer_content = [
                    m.content
                    for m in agent._history
                    if m.role == "user"
                    and not m.content.startswith("Turn ")
                    and not m.content.startswith("Begin.")
                ]
                injected = sum(
                    len(c.encode("utf-8")) for c in peer_content if "Coordination update" in c
                )
                unaccounted = [
                    c
                    for c in peer_content
                    if "Coordination update" not in c
                    and not c.startswith("Contents of")
                    and not c.startswith("That write was refused")
                    and not c.startswith("That call failed")
                    and not c.startswith("That reply could not be parsed")
                ]
                assert not unaccounted, (
                    f"peer content reached the model outside the channel: {unaccounted}"
                )
                # And what did arrive is within the accounted total: the
                # channel's own text plus the wrapper this agent adds.
                assert accounted > 0, "C2 received no coordination at all"
                assert injected >= accounted

            finally:
                harness.close()

    async def test_enforcement_blocks_a_model_write(self, tmp_path: Path) -> None:
        """C3 refuses a model's write to a path a peer holds.

        The gate does not know or care that a model produced the call,
        which is the property being checked.
        """
        with FakeModelServer() as server:
            server.queue_action(
                "agent_b",
                tool="write_file",
                arguments={"path": "src/schema.py", "content": "clobbered\n"},
            )
            harness = Harness(tmp_path, server, "C3", "local")
            try:
                harness.claims.acquire(
                    claim_id="c1",
                    path="src/schema.py",
                    agent_id="agent_a",
                    run_id="run_model",
                    now_us=1_700_000_000_000_000,
                    duration_us=10**9,
                )
                await harness.run(turns=1)
                denials = harness.claims.denials(run_id="run_model")
                assert denials, "a model write to a held path was not blocked"
                assert denials[0]["requesting_agent"] == "agent_b"
            finally:
                harness.close()


class TestFailureHandling:
    async def test_a_provider_error_does_not_take_down_the_run(self, tmp_path: Path) -> None:
        """§81: the endpoint failing is a run event, not a crash.

        A real HTTP 500, not a raised exception, so the transport's error
        path is exercised.
        """
        with FakeModelServer() as server:
            server.fail_next(500)
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=1)
                summary = harness.agents["agent_a"].summary()
                assert summary["transport_failures"] >= 1
                # The chain is still intact and verifiable.
                assert verify_chain(harness.relay.records(), harness.key_ring()).valid
            finally:
                harness.close()

    async def test_a_rate_limit_is_marked_retryable(self, tmp_path: Path) -> None:
        from causalmesh.adapters import HttpTransport, TransportError

        with FakeModelServer() as server:
            server.fail_next(429)
            transport = HttpTransport(base_url=server.base_url)
            with pytest.raises(TransportError) as info:
                transport.post_json("chat/completions", {})
            assert info.value.status == 429
            assert info.value.retryable

    async def test_a_bad_request_is_not_retryable(self, tmp_path: Path) -> None:
        from causalmesh.adapters import HttpTransport, TransportError

        with FakeModelServer() as server:
            server.fail_next(400)
            transport = HttpTransport(base_url=server.base_url)
            with pytest.raises(TransportError) as info:
                transport.post_json("chat/completions", {})
            assert not info.value.retryable

    async def test_protocol_violations_are_counted_not_fatal(self, tmp_path: Path) -> None:
        # A model that cannot follow the protocol is a measurement, not a
        # crash — and not something to silently work around either.
        with FakeModelServer() as server:
            for _ in range(3):
                server.queue_reply("agent_a", "I'll just describe my plan in prose.")
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=3)
                summary = harness.agents["agent_a"].summary()
                assert summary["protocol_failures"] >= 1
            finally:
                harness.close()

    async def test_a_persistently_noncompliant_model_stops(self, tmp_path: Path) -> None:
        # Bounded: otherwise a model stuck on prose burns the whole turn
        # budget and every token in it.
        with FakeModelServer() as server:
            for _ in range(6):
                server.queue_reply("agent_a", "no json here")
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=6)
                agent = harness.agents["agent_a"]
                assert agent._protocol_failures >= agent.max_protocol_failures
            finally:
                harness.close()


class TestAccounting:
    async def test_tokens_are_recorded_per_turn(self, tmp_path: Path) -> None:
        # §45 separates coordination cost from task-reasoning cost, which
        # needs per-turn attribution rather than a run total.
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=1)
                summary = harness.agents["agent_a"].summary()
                assert summary["prompt_tokens"] > 0
                assert summary["turn_records"][0]["prompt_tokens"] > 0
            finally:
                harness.close()

    async def test_the_model_settings_are_recorded(self, tmp_path: Path) -> None:
        # §43: every parameter that could change the output is a confound.
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=1)
                recorded = harness.agents["agent_a"].summary()["model"]
                assert recorded["temperature"] == 0.0
                assert recorded["model"] == "fake-model"
            finally:
                harness.close()

    async def test_the_summary_shape_matches_the_scripted_agent(self, tmp_path: Path) -> None:
        """Downstream analysis must not branch on agent kind.

        The fields that mean the same thing must be named the same, or
        every consumer of a run artifact needs a conditional.
        """
        with FakeModelServer() as server:
            server.queue_action("agent_a", tool="git_status", arguments={})
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                await harness.run(turns=1)
                summary = harness.agents["agent_a"].summary()
                shared = {
                    "agent_id",
                    "coordination",
                    "denied",
                    "failed",
                    "informed_paths",
                    "observations",
                    "turns",
                }
                assert shared <= set(summary)
            finally:
                harness.close()


class TestNoDirectToolAccess:
    async def test_the_agent_holds_no_toolbox(self, tmp_path: Path) -> None:
        """The containment property, checked on a live agent.

        `ModelAgent` reaches tools only through `ToolExecutor`, so model
        output cannot touch the filesystem without passing the gate — not
        by discipline, but because no attribute of the agent exposes a
        `Toolbox`.

        Checked on the object graph rather than by grepping source: an
        earlier version of this test searched the module text and failed on
        the docstring that explains the guarantee, which tests the prose
        rather than the code.
        """
        from causalmesh.tools import Toolbox

        with FakeModelServer() as server:
            harness = Harness(tmp_path, server, "C2", "local")
            try:
                agent = harness.agents["agent_a"]
                exposed = [
                    name for name, value in vars(agent).items() if isinstance(value, Toolbox)
                ]
                assert not exposed, f"agent exposes a Toolbox via {exposed}"
            finally:
                harness.close()

    def test_the_adapter_module_imports_no_execution_primitives(self) -> None:
        """No subprocess or filesystem module is reachable from the adapter.

        A tighter check than the object graph: even an unused import would
        mean a future edit could act outside the boundary without adding a
        dependency anyone would notice in review.
        """
        import causalmesh.adapters.model_agent as module

        forbidden = {"subprocess", "os", "shutil", "pathlib"}
        present = forbidden & set(vars(module))
        assert not present, f"model_agent imports {sorted(present)}"
