"""Delivery modes and the relay beyond four agents (spec §86).

The claims pinned here:

- a path-scoped agent receives exactly the events on paths it declared
  interest in, and no others;
- the four primary arms behave as they did (delivery, `RunConfig`
  serialisation, profile run counts);
- the relay is not limited to four participants, and broadcast fan-out grows
  quadratically where scoped fan-out does not.
"""

from __future__ import annotations

import pytest

from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.experiments import PROFILE_NAMES, profile
from causalmesh.relay import (
    BROADCAST,
    PATH_SCOPED,
    BroadcastDelivery,
    NullDelivery,
    PathScopedDelivery,
    Relay,
    policy_for_arm,
)
from causalmesh.tasks import RunConfig
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.unit

SEED = b"causalmesh-scaling-unit-seed-01"
RUN = "run_scaling"
BASE_TIME = 1_700_000_000_000_000


def agent_ids(count: int) -> tuple[str, ...]:
    return tuple(f"agent_{i:02d}" for i in range(count))


def make_relay(count: int, delivery) -> Relay:
    agents = agent_ids(count)
    return Relay(
        run_id=RUN,
        keypairs={agent: KeyPair.derive(SEED, agent) for agent in agents},
        delivery=delivery,
        participants=agents,
    )


def emit(relay: Relay, index: int, agent: str, paths: tuple[str, ...]):
    return relay.ingest(
        event_id=f"evt_{index:05d}",
        agent_id=agent,
        event_type=EventType.WRITE if paths else EventType.INTENT,
        identity=EventIdentity(
            experiment_id="exp_scaling",
            task_id="task_scaling",
            run_id=RUN,
            agent_id=agent,
            arm="C2",
        ),
        timestamp_us=BASE_TIME + index,
        paths=paths,
    )


class TestPathScopedDeliveryIsExact:
    """An agent gets the events on paths it declared, and nothing else."""

    def test_each_agent_receives_exactly_the_events_on_its_declared_paths(self) -> None:
        count = 12
        agents = agent_ids(count)
        # Agent i is interested in the path of agent i and of agent i+1 (mod N).
        interests = {
            agent: frozenset({f"src/p{i}.py", f"src/p{(i + 1) % count}.py"})
            for i, agent in enumerate(agents)
        }
        relay = make_relay(count, PathScopedDelivery(interests=interests))

        produced: list[tuple[str, tuple[str, ...]]] = []
        index = 0
        for round_ in range(3):
            for i, agent in enumerate(agents):
                paths = (f"src/p{i}.py",) if round_ % 2 == 0 else (f"src/p{i}.py", "src/common.py")
                assert emit(relay, index, agent, paths).accepted
                produced.append((agent, paths))
                index += 1

        for agent in agents:
            expected = [
                f"evt_{n:05d}"
                for n, (actor, paths) in enumerate(produced)
                if actor != agent and set(paths) & interests[agent]
            ]
            received = [event.event_id for event in relay.pending_for(agent)]
            assert received == expected, agent
            for event in relay.pending_for(agent):
                assert set(event.paths) & interests[agent], "delivered an uninteresting event"

    def test_an_agent_with_no_declared_interest_receives_only_pathless_events(self) -> None:
        relay = make_relay(3, PathScopedDelivery(interests={"agent_01": frozenset({"src/a.py"})}))
        emit(relay, 0, "agent_00", ("src/a.py",))
        emit(relay, 1, "agent_00", ())
        assert [e.event_id for e in relay.pending_for("agent_01")] == ["evt_00000", "evt_00001"]
        assert [e.event_id for e in relay.pending_for("agent_02")] == ["evt_00001"]

    def test_the_actor_never_receives_its_own_event(self) -> None:
        relay = make_relay(3, PathScopedDelivery(interests={"agent_00": frozenset({"src/a.py"})}))
        result = emit(relay, 0, "agent_00", ("src/a.py",))
        assert "agent_00" not in result.delivered_to
        assert relay.pending_for("agent_00") == ()

    def test_a_rename_reaches_an_agent_interested_in_either_end(self) -> None:
        relay = make_relay(3, PathScopedDelivery(interests={"agent_01": frozenset({"src/new.py"})}))
        assert emit(relay, 0, "agent_00", ("src/old.py", "src/new.py")).delivered_to == (
            "agent_01",
        )


class TestSelectingADeliveryMode:
    def test_omitting_the_mode_changes_nothing_for_the_primary_arms(self) -> None:
        assert isinstance(policy_for_arm("C0"), NullDelivery)
        for arm in ("C1", "C2", "C3"):
            assert isinstance(policy_for_arm(arm), BroadcastDelivery)

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    def test_broadcast_mode_is_the_default_policy(self, arm: str) -> None:
        assert isinstance(policy_for_arm(arm, mode=BROADCAST), BroadcastDelivery)

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    def test_path_scoped_mode_installs_the_scoped_policy(self, arm: str) -> None:
        interests = {"agent_00": frozenset({"src/a.py"})}
        policy = policy_for_arm(arm, mode=PATH_SCOPED, interests=interests)
        assert isinstance(policy, PathScopedDelivery)
        assert dict(policy.interests) == interests

    @pytest.mark.parametrize("mode", [None, BROADCAST, PATH_SCOPED])
    def test_c0_is_isolated_whatever_the_mode(self, mode: str | None) -> None:
        # No delivery mode may relax the isolation guarantee.
        assert isinstance(
            policy_for_arm("C0", mode=mode, interests={"agent_00": frozenset({"x"})}),
            NullDelivery,
        )

    def test_path_scoped_without_interests_refuses_rather_than_broadcasting(self) -> None:
        with pytest.raises(ValueError, match="interest map"):
            policy_for_arm("C2", mode=PATH_SCOPED)

    def test_an_unknown_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown delivery mode"):
            policy_for_arm("C2", mode="gossip")


class TestTheRelayIsNotLimitedToFourAgents:
    @pytest.mark.parametrize("count", [5, 8, 16, 32])
    def test_a_chain_of_n_agents_verifies_under_both_modes(self, count: int) -> None:
        agents = agent_ids(count)
        interests = {agent: frozenset({f"src/g{i // 4}.py"}) for i, agent in enumerate(agents)}
        for delivery in (BroadcastDelivery(), PathScopedDelivery(interests=interests)):
            relay = make_relay(count, delivery)
            for i, agent in enumerate(agents):
                assert emit(relay, i, agent, (f"src/g{i // 4}.py",)).accepted
            assert verify_chain(relay.records(), relay.key_ring()).valid
            assert relay.stats.events_ingested == count

    @pytest.mark.parametrize("count", [5, 16])
    def test_broadcast_delivers_every_event_to_every_peer(self, count: int) -> None:
        relay = make_relay(count, BroadcastDelivery())
        for i, agent in enumerate(agent_ids(count)):
            emit(relay, i, agent, ("src/x.py",))
        assert relay.stats.deliveries == count * (count - 1)

    def test_broadcast_fan_out_is_quadratic_and_scoped_is_not(self) -> None:
        # Each agent emits one event; scoped agents care about their group of
        # four. Pure relay arithmetic, no agents involved.
        totals = {}
        for count in (4, 8, 16, 32):
            agents = agent_ids(count)
            interests = {a: frozenset({f"src/g{i // 4}.py"}) for i, a in enumerate(agents)}
            deliveries = {}
            for name, delivery in (
                (BROADCAST, BroadcastDelivery()),
                (PATH_SCOPED, PathScopedDelivery(interests=interests)),
            ):
                relay = make_relay(count, delivery)
                for i, agent in enumerate(agents):
                    emit(relay, i, agent, (f"src/g{i // 4}.py",))
                deliveries[name] = relay.stats.deliveries
            totals[count] = deliveries
        assert [totals[n][BROADCAST] for n in (4, 8, 16, 32)] == [12, 56, 240, 992]
        assert [totals[n][PATH_SCOPED] for n in (4, 8, 16, 32)] == [12, 24, 48, 96]


class TestExistingBehaviourIsUnchanged:
    def test_run_config_serialises_as_before_when_no_mode_is_chosen(self) -> None:
        config = RunConfig(experiment_id="e", run_id="r", arm="C2", master_seed=b"x" * 32)
        assert "delivery_mode" not in config.to_dict()

    def test_run_config_records_a_chosen_mode(self) -> None:
        config = RunConfig(
            experiment_id="e",
            run_id="r",
            arm="C2",
            master_seed=b"x" * 32,
            delivery_mode=PATH_SCOPED,
        )
        assert config.to_dict()["delivery_mode"] == PATH_SCOPED

    def test_the_scalability_profiles_are_not_in_the_run_planning_registry(self) -> None:
        # `plan_experiment` multiplies tasks by arms by repetitions; adding a
        # profile with a different shape there would change what
        # `PROFILE_NAMES` and the CLI offer.
        assert PROFILE_NAMES == ("smoke", "pilot", "small", "medium", "confirmatory")
        assert profile("confirmatory", allow_gated=True).run_count(4) == 1920
        assert profile("smoke").run_count(4) == 4
