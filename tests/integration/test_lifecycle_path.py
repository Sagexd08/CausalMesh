"""The full lifecycle path, end to end (spec §13, §71).

    agent -> pre-hook -> gate -> tool -> post-hook -> event -> relay -> chain

This is the §71 vertical slice at the tool layer: a real workspace, real
files, the real gate, real events, and a chain that verifies offline
afterwards. Everything before this point tested components; this tests that
they compose.

The C3 case is the one that matters most. A denied write must leave three
things true at once: the file unchanged, an event recorded saying it was
denied, and the chain still verifiable. Any component could satisfy two of
those alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from causalmesh.claims import ClaimRegistry
from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.hooks import LifecycleBoundary, ToolOutcome, gate_for_arm
from causalmesh.isolation import build_run_workspaces
from causalmesh.relay import Relay, policy_for_arm
from causalmesh.tools import Toolbox, ToolExecutor
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.integration

SEED = b"causalmesh-lifecycle-integration"
RUN = "run_001"
AGENTS = ("agent_a", "agent_b")
BASE_TIME = 1_700_000_000_000_000
SECOND = 1_000_000


class Harness:
    """One arm's runtime: workspaces, relay, gate, boundary and executors."""

    def __init__(self, arm: str, tmp_path: Path) -> None:
        self.arm = arm
        fixture = tmp_path / "fixture"
        (fixture / "src").mkdir(parents=True, exist_ok=True)
        (fixture / "src" / "schema.py").write_text("# original\n", encoding="utf-8")

        self.workspaces = build_run_workspaces(
            base=tmp_path / arm / "workspace",
            run_id=RUN,
            agent_ids=list(AGENTS),
            fixture=fixture,
        )
        keypairs = {agent: KeyPair.derive(SEED, agent) for agent in AGENTS}
        self.claims = ClaimRegistry(tmp_path / arm / "claims.db") if arm == "C3" else None
        self.relay = Relay(
            run_id=RUN,
            keypairs=keypairs,
            delivery=policy_for_arm(arm),
            claims=self.claims,
            participants=AGENTS,
        )
        gate = gate_for_arm(arm, registry=self.claims, run_id=RUN)
        self.boundaries = {agent: LifecycleBoundary(gate=gate) for agent in AGENTS}
        self.executors = {
            agent: ToolExecutor(
                agent_id=agent,
                identity=EventIdentity(
                    experiment_id="exp_lifecycle",
                    task_id="task_lifecycle",
                    run_id=RUN,
                    agent_id=agent,
                    arm=arm,
                ),
                toolbox=Toolbox(self.workspaces[agent]),
                boundary=self.boundaries[agent],
                relay=self.relay,
            )
            for agent in AGENTS
        }

    def close(self) -> None:
        if self.claims is not None:
            self.claims.close()


@pytest.fixture
def c2(tmp_path: Path) -> Harness:
    harness = Harness("C2", tmp_path)
    yield harness
    harness.close()


@pytest.fixture
def c3(tmp_path: Path) -> Harness:
    harness = Harness("C3", tmp_path)
    yield harness
    harness.close()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestHappyPath:
    def test_a_read_then_write_produces_a_verifiable_chain(self, c2: Harness) -> None:
        agent_a = c2.executors["agent_a"]

        read = agent_a.call("read_file", now_us=BASE_TIME, paths=("src/schema.py",), path="src/schema.py")
        assert read.executed
        assert read.value == "# original\n"

        write = agent_a.call(
            "write_file",
            now_us=BASE_TIME + SECOND,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="# edited by agent_a\n",
        )
        assert write.executed

        # The file really changed.
        assert (
            c2.workspaces["agent_a"].resolve("src/schema.py").read_text() == "# edited by agent_a\n"
        )

        # And the chain records it, verifiably.
        result = verify_chain(c2.relay.records(), c2.relay.key_ring())
        assert result.valid, result.summary()
        assert result.events == 2
        assert [r["event"]["event_type"] for r in c2.relay.records()] == ["READ", "WRITE"]

    def test_every_tool_call_produces_exactly_one_event(self, c2: Harness) -> None:
        agent_a = c2.executors["agent_a"]
        for index in range(4):
            agent_a.call(
                "write_file",
                now_us=BASE_TIME + index * SECOND,
                paths=(f"src/file_{index}.py",),
                path=f"src/file_{index}.py",
                content=f"# {index}\n",
            )
        assert len(c2.relay.records()) == 4

    def test_the_recorded_paths_match_the_call(self, c2: Harness) -> None:
        c2.executors["agent_a"].call(
            "write_file",
            now_us=BASE_TIME,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="x\n",
        )
        assert c2.relay.records()[0]["event"]["paths"] == ["src/schema.py"]

    def test_an_unknown_tool_is_refused(self, c2: Harness) -> None:
        with pytest.raises(ValueError, match="unknown tool"):
            c2.executors["agent_a"].call("rm_rf", now_us=BASE_TIME)


class TestFailuresAreRecorded:
    def test_a_failed_tool_call_still_produces_an_event(self, c2: Harness) -> None:
        """§81: a failure is evidence, not garbage."""
        result = c2.executors["agent_a"].call(
            "read_file", now_us=BASE_TIME, paths=("missing.py",), path="missing.py"
        )
        assert result.outcome == ToolOutcome.FAILED

        records = c2.relay.records()
        assert len(records) == 1
        assert records[0]["event"]["event_type"] == str(EventType.FAILURE)
        assert records[0]["event"]["payload"]["outcome"] == "failed"

    def test_a_path_escape_attempt_is_recorded_as_a_failure(self, c2: Harness) -> None:
        # The attempt itself is evidence: an agent trying to reach a peer
        # workspace is a finding, not something to swallow silently.
        result = c2.executors["agent_a"].call(
            "read_file",
            now_us=BASE_TIME,
            paths=("../agent_b/secret.py",),
            path="../agent_b/secret.py",
        )
        assert result.outcome == ToolOutcome.FAILED
        assert "PathEscapeError" in (result.error or "")
        assert c2.relay.records()[0]["event"]["event_type"] == str(EventType.FAILURE)

    def test_the_chain_stays_verifiable_through_failures(self, c2: Harness) -> None:
        agent_a = c2.executors["agent_a"]
        agent_a.call("read_file", now_us=BASE_TIME, paths=("missing.py",), path="missing.py")
        agent_a.call(
            "write_file",
            now_us=BASE_TIME + SECOND,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="x\n",
        )
        assert verify_chain(c2.relay.records(), c2.relay.key_ring()).valid


class TestEnforcementPath:
    """The C3 case: denial must be simultaneously true in three places."""

    def test_a_denied_write_leaves_file_event_and_chain_all_consistent(
        self, c3: Harness
    ) -> None:
        assert c3.claims is not None
        target = c3.workspaces["agent_b"].resolve("src/schema.py")
        before = digest(target)

        # agent_a takes the claim.
        c3.claims.acquire(
            claim_id="c_a",
            path="src/schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=BASE_TIME,
            duration_us=120 * SECOND,
        )

        result = c3.executors["agent_b"].call(
            "write_file",
            now_us=BASE_TIME + SECOND,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="# agent_b overwrites\n",
        )

        # 1. The call was denied and the file is untouched.
        assert result.outcome == ToolOutcome.DENIED
        assert digest(target) == before

        # 2. The denial is recorded, with the holder named.
        records = c3.relay.records()
        assert len(records) == 1
        payload = records[0]["event"]["payload"]
        assert records[0]["event"]["event_type"] == str(EventType.FAILURE)
        assert payload["outcome"] == "denied"
        assert payload["holder_agent"] == "agent_a"
        assert payload["blocked_path"] == "src/schema.py"

        # 3. The chain still verifies.
        assert verify_chain(records, c3.relay.key_ring()).valid

    def test_the_holder_writes_successfully_under_the_same_gate(
        self, c3: Harness
    ) -> None:
        # Enforcement must block conflicting writers, not all writers.
        assert c3.claims is not None
        c3.claims.acquire(
            claim_id="c_a",
            path="src/schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=BASE_TIME,
            duration_us=120 * SECOND,
        )
        result = c3.executors["agent_a"].call(
            "write_file",
            now_us=BASE_TIME + SECOND,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="# holder writes\n",
        )
        assert result.executed

    def test_c2_permits_the_same_write_c3_denies(
        self, c2: Harness, c3: Harness
    ) -> None:
        """The enforcement factor, isolated: same call, both arms."""
        assert c3.claims is not None
        c3.claims.acquire(
            claim_id="c_a",
            path="src/schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=BASE_TIME,
            duration_us=120 * SECOND,
        )

        arguments = dict(
            paths=("src/schema.py",), path="src/schema.py", content="# overwritten\n"
        )
        c2_result = c2.executors["agent_b"].call(
            "write_file", now_us=BASE_TIME + SECOND, **arguments
        )
        c3_result = c3.executors["agent_b"].call(
            "write_file", now_us=BASE_TIME + SECOND, **arguments
        )

        assert c2_result.executed
        assert c3_result.outcome == ToolOutcome.DENIED
        assert (
            c2.workspaces["agent_b"].resolve("src/schema.py").read_text()
            == "# overwritten\n"
        )
        assert (
            c3.workspaces["agent_b"].resolve("src/schema.py").read_text() == "# original\n"
        )


class TestCausalParents:
    def test_an_observed_peer_event_becomes_the_causal_parent(
        self, c2: Harness
    ) -> None:
        """§57: what an agent knew before it acted must be reconstructible."""
        c2.executors["agent_a"].call(
            "write_file",
            now_us=BASE_TIME,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="# by a\n",
        )

        observed = c2.executors["agent_b"].observe(BASE_TIME + SECOND)
        assert len(observed) == 1

        c2.executors["agent_b"].call(
            "write_file",
            now_us=BASE_TIME + 2 * SECOND,
            paths=("src/api.py",),
            path="src/api.py",
            content="# by b, after seeing a\n",
        )

        records = c2.relay.records()
        assert records[1]["event"]["parent_id"] == observed[0].event_id

    def test_c0_agents_observe_nothing(self, tmp_path: Path) -> None:
        harness = Harness("C0", tmp_path)
        try:
            harness.executors["agent_a"].call(
                "write_file",
                now_us=BASE_TIME,
                paths=("src/schema.py",),
                path="src/schema.py",
                content="# by a\n",
            )
            assert harness.executors["agent_b"].observe(BASE_TIME + SECOND) == ()

            harness.executors["agent_b"].call(
                "write_file",
                now_us=BASE_TIME + 2 * SECOND,
                paths=("src/api.py",),
                path="src/api.py",
                content="# by b\n",
            )
            assert harness.relay.records()[1]["event"]["parent_id"] is None
        finally:
            harness.close()


class TestAccounting:
    def test_the_boundary_counts_every_outcome(self, c3: Harness) -> None:
        assert c3.claims is not None
        c3.claims.acquire(
            claim_id="c_a",
            path="src/schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=BASE_TIME,
            duration_us=120 * SECOND,
        )
        agent_b = c3.executors["agent_b"]
        agent_b.call("read_file", now_us=BASE_TIME, paths=("src/schema.py",), path="src/schema.py")
        agent_b.call(
            "write_file",
            now_us=BASE_TIME + SECOND,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="x",
        )
        agent_b.call("read_file", now_us=BASE_TIME + 2 * SECOND, paths=("gone.py",), path="gone.py")

        summary = c3.boundaries["agent_b"].summary()
        assert summary == {
            "calls": 3,
            "executed": 1,
            "denied": 1,
            "failed": 1,
            "hook_latency_p50_us": summary["hook_latency_p50_us"],
            "hook_latency_p99_us": summary["hook_latency_p99_us"],
        }

    def test_the_relay_summary_reflects_the_calls(self, c2: Harness) -> None:
        c2.executors["agent_a"].call(
            "write_file",
            now_us=BASE_TIME,
            paths=("src/schema.py",),
            path="src/schema.py",
            content="x",
        )
        assert c2.relay.summary()["stats"]["events_ingested"] == 1
