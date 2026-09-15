"""Channels wired into the four-arm runtime (spec §14 to §18, §96).

The unit tests check each channel alone. This module runs the *same scripted
history* through all four arms with real relays and real channels, and
answers the first four questions of §96 from the resulting accounting:

    C0 received no coordination information
    C1 received transcript information
    C2 received bounded structured metadata
    C3 received the same metadata, plus enforcement

Running one history through every arm is what makes an unintended third
difference detectable; checking each arm alone could not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.channels import (
    ChannelError,
    MetadataChannel,
    NullChannel,
    Room,
    TranscriptChannel,
)
from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.relay import Relay, policy_for_arm
from causalmesh.relevance import AgentInterests
from causalmesh.verifier import parse_record

pytestmark = pytest.mark.integration

SEED = b"causalmesh-channel-arms-seed-001"
RUN = "run_001"
AGENTS = ("agent_a", "agent_b")
BASE_TIME = 1_700_000_000_000_000
SECOND = 1_000_000
ARMS = ("C0", "C1", "C2", "C3")
WINDOW = 8

# agent_a edits the schema repeatedly; agent_b depends on it. Long enough for
# C1's quadratic growth to separate from C2's linear cost.
TURNS = 10


def make_channel(arm: str, agent_id: str, room: Room):
    if arm == "C0":
        return NullChannel(agent_id)
    if arm == "C1":
        return TranscriptChannel(agent_id, room)
    return MetadataChannel(
        agent_id,
        arm=arm,
        window=WINDOW,
        interests=AgentInterests(
            agent_id=agent_id,
            owned_paths=frozenset({"src/api.py"}),
            dependency_paths=frozenset({"src/schema.py"}),
        ),
    )


class ArmRun:
    """One arm's relay plus channels, driven through the same history."""

    def __init__(self, arm: str, tmp_path: Path) -> None:
        self.arm = arm
        keypairs = {agent: KeyPair.derive(SEED, agent) for agent in AGENTS}
        self.claims = ClaimRegistry(tmp_path / f"{arm}.db") if arm == "C3" else None
        self.relay = Relay(
            run_id=RUN,
            keypairs=keypairs,
            delivery=policy_for_arm(arm),
            claims=self.claims,
            participants=AGENTS,
        )
        self.room = Room(RUN, "task_channels")
        self.channels = {agent: make_channel(arm, agent, self.room) for agent in AGENTS}

    def play(self) -> ArmRun:
        for turn in range(TURNS):
            # agent_a writes the schema.
            self.relay.ingest(
                event_id=f"evt_a_{turn:04d}",
                agent_id="agent_a",
                event_type=EventType.WRITE,
                identity=EventIdentity(
                    experiment_id="exp_channels",
                    task_id="task_channels",
                    run_id=RUN,
                    agent_id="agent_a",
                    arm=self.arm,
                ),
                timestamp_us=BASE_TIME + turn * SECOND,
                paths=("src/schema.py",),
            )
            # agent_b takes whatever its channel gives it.
            delivered = self.relay.drain("agent_b")
            self.channels["agent_b"].offer(delivered, turn=turn)
        return self

    def close(self) -> None:
        if self.claims is not None:
            self.claims.close()


@pytest.fixture
def arms(tmp_path: Path) -> dict[str, ArmRun]:
    runs = {arm: ArmRun(arm, tmp_path).play() for arm in ARMS}
    yield runs
    for run in runs.values():
        run.close()


def accounting(runs: dict[str, ArmRun], arm: str):
    return runs[arm].channels["agent_b"].accounting


class TestQuestionOneC0ReceivedNothing:
    """§96: can we prove C0 received no coordination information?"""

    def test_c0_accounting_reports_a_provable_zero(self, arms: dict[str, ArmRun]) -> None:
        c0 = accounting(arms, "C0")
        assert c0.received_no_coordination
        assert c0.total_bytes == 0
        assert c0.total_tokens == 0
        assert c0.events_available == 0
        assert c0.events_injected == 0

    def test_c0_recorded_a_digest_for_every_turn(self, arms: dict[str, ArmRun]) -> None:
        # A positive audit trail rather than an absent one.
        assert len(accounting(arms, "C0").digests) == TURNS

    def test_the_other_arms_are_not_isolated(self, arms: dict[str, ArmRun]) -> None:
        # Without this the C0 assertion could pass because nothing worked.
        for arm in ("C1", "C2", "C3"):
            assert not accounting(arms, arm).received_no_coordination

    def test_a_c0_channel_offered_events_raises(self, arms: dict[str, ArmRun]) -> None:
        """Contamination fails loudly rather than being silently absorbed.

        Simulates the failure this guards against: the relay's NullDelivery
        having been bypassed, so a real peer event reaches a C0 channel. The
        run is then contaminated, not merely misconfigured, and must not be
        allowed to complete looking valid.
        """
        leaked = parse_record(arms["C2"].relay.records()[0]).event
        with pytest.raises(ChannelError, match="must receive none"):
            arms["C0"].channels["agent_b"].offer((leaked,), turn=0)


class TestQuestionTwoC1ReceivedTranscript:
    def test_c1_injected_prose(self, arms: dict[str, ArmRun]) -> None:
        assert accounting(arms, "C1").total_bytes > 0
        assert len(arms["C1"].room) == TURNS

    def test_c1_replays_the_whole_history_each_turn(self, arms: dict[str, ArmRun]) -> None:
        # Injections total 1+2+...+T rather than T.
        c1 = accounting(arms, "C1")
        assert c1.events_injected == TURNS * (TURNS + 1) // 2

    def test_c1_never_dropped_anything(self, arms: dict[str, ArmRun]) -> None:
        # §15 forbids silent truncation.
        assert accounting(arms, "C1").events_dropped == 0


class TestQuestionThreeC2ReceivedBoundedMetadata:
    def test_c2_never_exceeded_the_window(self, arms: dict[str, ArmRun]) -> None:
        c2 = accounting(arms, "C2")
        assert c2.events_injected <= WINDOW * TURNS
        assert c2.events_injected == TURNS  # one event per turn, well under w

    def test_c2_availability_is_tracked_separately(self, arms: dict[str, ArmRun]) -> None:
        # §18: "never told" must stay distinguishable from "told but cut".
        c2 = accounting(arms, "C2")
        assert c2.events_available == TURNS
        assert c2.events_injected == TURNS

    def test_a_narrow_window_drops_events_and_says_so(self, arms: dict[str, ArmRun]) -> None:
        # Offer a whole run's worth of real events to a window of 2: the
        # dropped count must be reported, not silently absorbed.
        events = tuple(parse_record(r).event for r in arms["C2"].relay.records())
        injection = MetadataChannel("agent_b", window=2).offer(events, turn=0)
        assert injection.events_available == len(events)
        assert injection.events_injected == 2
        assert injection.events_dropped == len(events) - 2


class TestQuestionFourC3AddsEnforcementOnly:
    def test_c3_and_c2_received_identical_information(self, arms: dict[str, ArmRun]) -> None:
        """The C2→C3 contrast must isolate enforcement.

        Identical per-turn digests are the strongest available evidence that
        the two arms saw byte-for-byte the same context.
        """
        c2, c3 = accounting(arms, "C2"), accounting(arms, "C3")
        assert c2.digests == c3.digests
        assert c2.total_bytes == c3.total_bytes
        assert c2.events_injected == c3.events_injected

    def test_only_c3_has_a_claim_registry(self, arms: dict[str, ArmRun]) -> None:
        assert arms["C2"].claims is None
        assert arms["C3"].claims is not None

    def test_c3_enforces_where_c2_does_not(self, arms: dict[str, ArmRun]) -> None:
        registry = arms["C3"].claims
        assert registry is not None
        registry.acquire(
            claim_id="c_a",
            path="src/schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=BASE_TIME,
            duration_us=120 * SECOND,
        )
        assert (
            not arms["C3"]
            .relay.may_write(path="src/schema.py", agent_id="agent_b", now_us=BASE_TIME + SECOND)
            .granted
        )
        assert (
            arms["C2"]
            .relay.may_write(path="src/schema.py", agent_id="agent_b", now_us=BASE_TIME + SECOND)
            .granted
        )


class TestCostSeparation:
    def test_c1_costs_far_more_than_c2_over_the_run(self, arms: dict[str, ArmRun]) -> None:
        """§46: the coordination-cost ratio the experiment predicts."""
        c1 = accounting(arms, "C1").total_bytes
        c2 = accounting(arms, "C2").total_bytes
        assert c1 > c2
        # At T=10 the quadratic term already dominates.
        assert c1 / c2 > 2

    def test_coordination_tokens_are_ordered_c0_lt_c2_lt_c1(self, arms: dict[str, ArmRun]) -> None:
        # §45: coordination cost must be separable and comparable per arm.
        c0 = accounting(arms, "C0").total_tokens
        c1 = accounting(arms, "C1").total_tokens
        c2 = accounting(arms, "C2").total_tokens
        assert c0 == 0
        assert c0 < c2 < c1
