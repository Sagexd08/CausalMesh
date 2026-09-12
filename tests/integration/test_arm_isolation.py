"""The four arms, observed rather than assumed (spec §14, §73, §96).

§96 asks four questions this module answers executably:

    Can we prove C0 received no coordination information?
    Can we prove C1 received transcript information?
    Can we prove C2 received bounded structured metadata?
    Can we prove C3 additionally enforced write claims?

The design point being tested is that the arms differ in exactly two factors
— information and enforcement — and in nothing else. So each test runs the
*same scripted history* through every arm and compares what changed. A test
that only checked C0 in isolation could not detect an arm accidentally
differing in a third way.

Channel-level representation (transcript versus bounded metadata) arrives in
Step 7. What is provable at the relay layer today is delivery and
enforcement, and the tests say so rather than overclaiming.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.relay import Relay, policy_for_arm
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.integration

SEED = b"causalmesh-arm-isolation-seed-01"
RUN = "run_001"
AGENTS = ("agent_a", "agent_b")
BASE_TIME = 1_700_000_000_000_000
ARMS = ("C0", "C1", "C2", "C3")

# One history, replayed identically under every arm. Agent A edits the schema;
# agent B reads it and writes a dependent file.
SCRIPT: tuple[tuple[str, EventType, tuple[str, ...]], ...] = (
    ("agent_a", EventType.READ, ("src/schema.py",)),
    ("agent_a", EventType.WRITE, ("src/schema.py",)),
    ("agent_b", EventType.READ, ("src/schema.py",)),
    ("agent_b", EventType.WRITE, ("src/api.py",)),
)


class ArmRun:
    """One run of the scripted history under one arm."""

    def __init__(self, arm: str, tmp_path: Path) -> None:
        self.arm = arm
        keypairs = {agent: KeyPair.derive(SEED, agent) for agent in AGENTS}
        # Only C3 installs a claim registry: enforcement is the C2→C3 factor.
        self.claims = ClaimRegistry(tmp_path / f"{arm}_claims.db") if arm == "C3" else None
        self.relay = Relay(
            run_id=RUN,
            keypairs=keypairs,
            delivery=policy_for_arm(arm),
            claims=self.claims,
            participants=AGENTS,
        )
        # `delivered` is what the relay sent; `observed` is what each agent
        # actually consumed. They coincide here, but keeping them apart makes
        # "was it delivered" and "was it seen" separately checkable.
        self.delivered: dict[str, list[str]] = {agent: [] for agent in AGENTS}
        self.observed: dict[str, list[str]] = {agent: [] for agent in AGENTS}

    def play(self) -> ArmRun:
        for index, (agent, event_type, paths) in enumerate(SCRIPT):
            # An agent reacts to whatever the relay delivered to it, exactly
            # as a real agent would: it drains its inbox and records the last
            # peer event it saw as the causal parent of what it does next.
            # This is what makes the parent chain evidence of what an agent
            # *could have known* (§57) rather than decoration — and it is why
            # C0, which is delivered nothing, can never have a parent.
            delivered = self.relay.drain(agent)
            self.observed[agent].extend(event.event_id for event in delivered)
            parent_id = delivered[-1].event_id if delivered else None

            result = self.relay.ingest(
                event_id=f"evt_{index:04d}",
                agent_id=agent,
                event_type=event_type,
                identity=EventIdentity(
                    experiment_id="exp_arms",
                    task_id="task_arms",
                    run_id=RUN,
                    agent_id=agent,
                    arm=self.arm,
                ),
                timestamp_us=BASE_TIME + index * 1_000,
                paths=paths,
                parent_id=parent_id,
            )
            assert result.accepted, result.reason
            for recipient in result.delivered_to:
                self.delivered[recipient].append(f"evt_{index:04d}")
        return self

    def close(self) -> None:
        if self.claims is not None:
            self.claims.close()


@pytest.fixture
def arm_runs(tmp_path: Path) -> dict[str, ArmRun]:
    runs = {arm: ArmRun(arm, tmp_path).play() for arm in ARMS}
    yield runs
    for run in runs.values():
        run.close()


class TestInformationFactor:
    """C0 versus the informed arms: the information manipulation."""

    def test_c0_receives_no_coordination_data(self, arm_runs: dict[str, ArmRun]) -> None:
        """§14, §96: C0's isolation, proved from the record."""
        c0 = arm_runs["C0"]
        assert all(events == [] for events in c0.delivered.values())
        assert all(c0.relay.pending_for(agent) == () for agent in AGENTS)
        assert c0.relay.stats.deliveries == 0

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    def test_informed_arms_receive_peer_events(
        self, arm_runs: dict[str, ArmRun], arm: str
    ) -> None:
        run = arm_runs[arm]
        assert run.relay.stats.deliveries > 0
        # Each agent sees exactly the peer's events, never its own.
        assert run.delivered["agent_b"] == ["evt_0000", "evt_0001"]
        assert run.delivered["agent_a"] == ["evt_0002", "evt_0003"]

    def test_the_information_factor_is_the_only_delivery_difference(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        # C1, C2 and C3 must be identical in *delivery*; they differ in
        # representation and enforcement, not in who receives what.
        informed = [arm_runs[arm].delivered for arm in ("C1", "C2", "C3")]
        assert informed[0] == informed[1] == informed[2]
        assert arm_runs["C0"].delivered != informed[0]


class TestEnforcementFactor:
    """C2 versus C3: the enforcement manipulation."""

    @pytest.mark.parametrize("arm", ["C0", "C1", "C2"])
    def test_unenforced_arms_permit_every_write(
        self, arm_runs: dict[str, ArmRun], arm: str
    ) -> None:
        outcome = arm_runs[arm].relay.may_write(
            path="src/schema.py", agent_id="agent_b", now_us=BASE_TIME
        )
        assert outcome.granted
        assert "no claim registry" in outcome.reason

    def test_c3_enforces_claims(self, arm_runs: dict[str, ArmRun]) -> None:
        c3 = arm_runs["C3"]
        assert c3.claims is not None
        c3.claims.acquire(
            claim_id="c_a",
            path="src/schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=BASE_TIME,
            duration_us=120_000_000,
        )
        outcome = c3.relay.may_write(
            path="src/schema.py", agent_id="agent_b", now_us=BASE_TIME + 1_000
        )
        assert not outcome.granted
        assert outcome.holder is not None
        assert outcome.holder.agent_id == "agent_a"

    def test_enforcement_is_the_only_difference_between_c2_and_c3(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        """The C2→C3 contrast must isolate enforcement alone."""
        c2, c3 = arm_runs["C2"], arm_runs["C3"]
        assert c2.delivered == c3.delivered
        assert c2.relay.stats.deliveries == c3.relay.stats.deliveries
        # The one difference: a claim registry is installed.
        assert c2.claims is None
        assert c3.claims is not None


class TestHeldConstant:
    """§3: everything other than the manipulated factors must be identical."""

    def test_every_arm_records_the_same_events(self, arm_runs: dict[str, ArmRun]) -> None:
        per_arm = {
            arm: [
                (r["event"]["event_type"], tuple(r["event"]["paths"]), r["event"]["sequence"])
                for r in run.relay.records()
            ]
            for arm, run in arm_runs.items()
        }
        assert len({tuple(events) for events in per_arm.values()}) == 1

    def test_every_arm_produces_a_verifiable_chain(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        for arm, run in arm_runs.items():
            result = verify_chain(run.relay.records(), run.relay.key_ring())
            assert result.valid, f"{arm}: {result.summary()}"
            assert result.events == len(SCRIPT)

    def test_each_chain_is_labelled_with_its_own_arm(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        # Every event carries its arm, so evidence from two arms can never be
        # pooled by accident (§43).
        for arm, run in arm_runs.items():
            assert all(r["event"]["identity"]["arm"] == arm for r in run.relay.records())

        heads = {run.relay.head_hash for run in arm_runs.values()}
        assert len(heads) == len(ARMS)

    def test_the_work_performed_is_identical_across_arms(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        """§3: the task, the actors and the file operations are held constant.

        Only two things may vary between arms: the recorded arm label, and
        the causal parent — the latter *because* it records what a peer
        delivered, which is precisely the information manipulation. Every
        other field must match, or some third factor is varying and the
        contrasts no longer isolate what they claim to.
        """

        def work(run: ArmRun) -> list[tuple]:
            return [
                (
                    r["event"]["event_id"],
                    r["event"]["event_type"],
                    r["event"]["identity"]["agent_id"],
                    tuple(r["event"]["paths"]),
                    r["event"]["sequence"],
                    r["event"]["timestamp_us"],
                    r["event"]["payload"],
                    tuple(r["event"]["references"]),
                )
                for r in run.relay.records()
            ]

        rendered = {str(work(run)) for run in arm_runs.values()}
        assert len(rendered) == 1, "arms diverged in something other than the two factors"

    def test_causal_parents_vary_only_with_the_information_factor(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        # The one legitimate difference: C0 records no parents because it is
        # delivered nothing, while the informed arms record the peer event
        # each agent was reacting to. C1, C2 and C3 must agree exactly.
        parents = {
            arm: [r["event"]["parent_id"] for r in run.relay.records()]
            for arm, run in arm_runs.items()
        }
        assert parents["C1"] == parents["C2"] == parents["C3"]
        assert parents["C0"] != parents["C1"]
        assert parents["C0"] == [None] * len(SCRIPT)


class TestOfflineEvidence:
    def test_each_arm_exports_independently_verifiable_evidence(
        self, arm_runs: dict[str, ArmRun], tmp_path: Path
    ) -> None:
        # Every arm's claim about what it did must survive leaving the system.
        for arm, run in arm_runs.items():
            paths = run.relay.export(tmp_path / "exports" / arm)
            assert paths["chain"].exists()
            assert paths["keyring"].exists()

    def test_c0_isolation_is_visible_in_the_exported_record(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        """The strongest form of the §14 claim: it survives export.

        Delivery counts live in the relay, so a reader of the raw chain alone
        cannot see them. What the chain *does* show is the causal parent each
        agent recorded — the peer event it was reacting to. C0 agents are
        delivered nothing, so they can never record one.

        The informed arms are asserted alongside deliberately. Without that
        comparison this test would pass even if no arm ever set a parent,
        proving nothing about C0.
        """
        c0_parents = [r["event"]["parent_id"] for r in arm_runs["C0"].relay.records()]
        assert c0_parents == [None] * len(SCRIPT)

        for arm in ("C1", "C2", "C3"):
            parents = [r["event"]["parent_id"] for r in arm_runs[arm].relay.records()]
            assert any(parent is not None for parent in parents), (
                f"{arm} recorded no causal parents, so C0 having none proves nothing"
            )

    def test_only_informed_agents_observed_peer_events(
        self, arm_runs: dict[str, ArmRun]
    ) -> None:
        # The consumption side of the same claim: C0 agents drained empty
        # inboxes every turn.
        assert all(seen == [] for seen in arm_runs["C0"].observed.values())
        for arm in ("C1", "C2", "C3"):
            assert any(seen for seen in arm_runs[arm].observed.values())
