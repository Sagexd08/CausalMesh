"""Claim exclusivity under real concurrency (spec §19, §20, §84).

The §20 invariant — at most one valid writer claim per path at any instant —
is the entire basis of the C3 arm. The unit tests establish it for sequential
calls; this module attacks it with genuine contention.

Two levels, because they falsify different things:

- **Threads** hammer one registry object, exercising the transaction boundary
  under interleaving.
- **Processes** hammer one database *file*. This is the level that matters:
  agents run as separate OS processes (§11), so an in-process lock would
  enforce nothing across the boundary the experiment actually puts them on. A
  test that only ran threads could pass with a mechanism that fails in the
  real configuration.
"""

from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from causalmesh.claims import ClaimRegistry, ClaimStatus

pytestmark = pytest.mark.property

SECOND = 1_000_000
RUN = "run_001"
SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


# Runs in a separate OS process, contending for the same database file.
CONTENDER_PROGRAM = """
import json, sys
from causalmesh.claims import ClaimRegistry

database, agent_id, path, now_us, duration_us = sys.argv[1:6]
with ClaimRegistry(database) as registry:
    outcome = registry.acquire(
        claim_id=f"claim_{agent_id}",
        path=path,
        agent_id=agent_id,
        run_id="run_001",
        now_us=int(now_us),
        duration_us=int(duration_us),
    )
print(json.dumps({"agent": agent_id, "granted": outcome.granted}))
"""


class TestThreadedContention:
    @pytest.mark.parametrize("contenders", [2, 4, 8, 16])
    def test_exactly_one_thread_wins_a_contested_path(self, contenders: int) -> None:
        with ClaimRegistry() as registry:

            def attempt(index: int) -> bool:
                return registry.acquire(
                    claim_id=f"c{index}",
                    path="src/contested.py",
                    agent_id=f"agent_{index}",
                    run_id=RUN,
                    now_us=0,
                    duration_us=120 * SECOND,
                ).granted

            with ThreadPoolExecutor(max_workers=contenders) as pool:
                results = list(pool.map(attempt, range(contenders)))

            assert sum(results) == 1
            assert len(registry.active_claims(run_id=RUN, now_us=SECOND)) == 1

    def test_every_loser_is_recorded_as_a_denial(self) -> None:
        # The denial count is the enforcement measurement; a lost denial would
        # understate the cost of C3.
        contenders = 8
        with ClaimRegistry() as registry:

            def attempt(index: int) -> bool:
                return registry.acquire(
                    claim_id=f"c{index}",
                    path="src/contested.py",
                    agent_id=f"agent_{index}",
                    run_id=RUN,
                    now_us=0,
                    duration_us=120 * SECOND,
                ).granted

            with ThreadPoolExecutor(max_workers=contenders) as pool:
                granted = sum(pool.map(attempt, range(contenders)))

            assert granted == 1
            assert len(registry.denials(run_id=RUN)) == contenders - 1

    def test_contention_across_distinct_paths_never_blocks(self) -> None:
        with ClaimRegistry() as registry:

            def attempt(index: int) -> bool:
                return registry.acquire(
                    claim_id=f"c{index}",
                    path=f"src/file_{index}.py",
                    agent_id=f"agent_{index}",
                    run_id=RUN,
                    now_us=0,
                    duration_us=120 * SECOND,
                ).granted

            with ThreadPoolExecutor(max_workers=8) as pool:
                assert all(pool.map(attempt, range(8)))


class TestCrossProcessContention:
    """The level that matters: separate OS processes, one database file."""

    @pytest.mark.parametrize("contenders", [2, 4])
    def test_exactly_one_process_wins_a_contested_path(
        self, tmp_path: Path, contenders: int
    ) -> None:
        database = tmp_path / "claims.db"
        # Create the schema first so contenders race on acquisition, not on
        # table creation.
        ClaimRegistry(database).close()

        processes = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    CONTENDER_PROGRAM,
                    str(database),
                    f"agent_{index}",
                    "src/contested.py",
                    "0",
                    str(120 * SECOND),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={"PYTHONPATH": str(SRC_ROOT), **_inherited_env()},
            )
            for index in range(contenders)
        ]
        outcomes = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, f"contender failed:\n{stderr}"
            outcomes.append(json.loads(stdout))

        assert sum(1 for o in outcomes if o["granted"]) == 1, outcomes

        with ClaimRegistry(database) as registry:
            assert len(registry.active_claims(run_id=RUN, now_us=SECOND)) == 1

    def test_a_claim_written_by_another_process_blocks_this_one(self, tmp_path: Path) -> None:
        database = tmp_path / "claims.db"
        ClaimRegistry(database).close()

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                CONTENDER_PROGRAM,
                str(database),
                "agent_remote",
                "src/schema.py",
                "0",
                str(120 * SECOND),
            ],
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(SRC_ROOT), **_inherited_env()},
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["granted"] is True

        with ClaimRegistry(database) as registry:
            outcome = registry.may_write(
                path="src/schema.py", agent_id="agent_local", run_id=RUN, now_us=SECOND
            )
            assert not outcome.granted
            assert outcome.holder is not None
            assert outcome.holder.agent_id == "agent_remote"


def _inherited_env() -> dict[str, str]:
    """Inherit the ambient environment so the subprocess finds its interpreter."""
    import os

    return {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}


# A generated schedule of claim operations against a small set of paths and
# agents, so the invariant is checked against interleavings nobody wrote by
# hand.
operations = st.lists(
    st.tuples(
        st.sampled_from(["acquire", "release", "renew"]),
        st.sampled_from(["src/a.py", "src/b.py"]),
        st.sampled_from(["agent_a", "agent_b", "agent_c"]),
        st.integers(min_value=0, max_value=20),  # time step
        st.integers(min_value=1, max_value=10),  # lease length in steps
    ),
    min_size=1,
    max_size=25,
)


@given(operations)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_no_schedule_can_produce_two_live_claims_on_a_path(
    schedule: list[tuple[str, str, str, int, int]],
) -> None:
    """§20 must hold after every operation, under any generated schedule."""
    with ClaimRegistry() as registry:
        claims_by_agent: dict[tuple[str, str], str] = {}

        for index, (operation, path, agent, step, length) in enumerate(schedule):
            now = step * SECOND

            if operation == "acquire":
                outcome = registry.acquire(
                    claim_id=f"c{index}",
                    path=path,
                    agent_id=agent,
                    run_id=RUN,
                    now_us=now,
                    duration_us=length * SECOND,
                )
                if outcome.granted and outcome.claim is not None:
                    claims_by_agent[(agent, path)] = outcome.claim.claim_id
            elif operation == "release":
                claim_id = claims_by_agent.pop((agent, path), None)
                if claim_id:
                    registry.release(claim_id=claim_id, agent_id=agent, now_us=now)
            else:
                claim_id = claims_by_agent.get((agent, path))
                if claim_id:
                    registry.renew(
                        claim_id=claim_id,
                        agent_id=agent,
                        now_us=now,
                        duration_us=length * SECOND,
                    )

            # The invariant, checked at this instant and at every later one
            # the schedule can reach.
            for probe_step in range(step, 22):
                probe = probe_step * SECOND
                for probe_path in ("src/a.py", "src/b.py"):
                    live = [
                        claim
                        for claim in registry.history(run_id=RUN)
                        if claim.path == probe_path
                        and claim.status == ClaimStatus.ACTIVE
                        and claim.expires_at_us > probe
                        and claim.issued_at_us <= probe
                    ]
                    assert len(live) <= 1, (
                        f"invariant violated on {probe_path} at {probe}: "
                        f"{[c.claim_id for c in live]}"
                    )


@given(
    st.lists(
        st.tuples(st.sampled_from(["agent_a", "agent_b"]), st.integers(0, 4)),
        min_size=1,
        max_size=12,
    )
)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_every_denial_names_a_holder_that_really_held_the_path(
    attempts: list[tuple[str, int]],
) -> None:
    """A denial must be traceable to evidence (§52), never inferred.

    The generated times are *gaps* accumulated into a monotonic timeline
    rather than absolute instants. A real run's clock never goes backwards,
    and feeding the registry out-of-order timestamps would test a scenario
    that cannot occur while making the "held at that instant" assertion
    meaningless.
    """
    with ClaimRegistry() as registry:
        now = 0
        for index, (agent, gap) in enumerate(attempts):
            now += gap * SECOND
            registry.acquire(
                claim_id=f"c{index}",
                path="src/contested.py",
                agent_id=agent,
                run_id=RUN,
                now_us=now,
                duration_us=5 * SECOND,
            )

        history = {claim.claim_id: claim for claim in registry.history(run_id=RUN)}
        for denial in registry.denials(run_id=RUN):
            holder = history[denial["holder_claim_id"]]
            assert holder.agent_id == denial["holder_agent"]
            assert holder.agent_id != denial["requesting_agent"]
            # The named holder must genuinely have been live at that instant.
            assert holder.issued_at_us <= denial["timestamp_us"] < holder.expires_at_us
