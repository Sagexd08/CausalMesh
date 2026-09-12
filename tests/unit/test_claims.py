"""Unit tests for the claim registry (spec §19, §20, §21).

The invariant under test is §20: at most one valid writer claim may exist for
a path at any instant. Everything else here exists to make that invariant
measurable — denials, expiry, renewal and history are what the C2→C3 contrast
is computed from.

Time is passed explicitly throughout, so expiry is exercised deterministically
rather than by sleeping.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.claims import Claim, ClaimError, ClaimRegistry, ClaimStatus

pytestmark = pytest.mark.unit

SECOND = 1_000_000
RUN = "run_001"
LEASE = 120 * SECOND  # the §21 default lease duration


@pytest.fixture
def registry() -> ClaimRegistry:
    with ClaimRegistry() as reg:
        yield reg


def acquire(
    registry: ClaimRegistry,
    claim_id: str,
    path: str,
    agent: str,
    now: int,
    duration: int = LEASE,
    run: str = RUN,
):
    return registry.acquire(
        claim_id=claim_id, path=path, agent_id=agent, run_id=run, now_us=now, duration_us=duration
    )


class TestExclusivity:
    """§20: at most one valid writer claim per path at any instant."""

    def test_a_free_path_is_granted(self, registry: ClaimRegistry) -> None:
        outcome = acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        assert outcome.granted
        assert outcome.claim is not None
        assert outcome.claim.status == ClaimStatus.ACTIVE

    def test_a_held_path_is_denied_to_another_agent(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        outcome = acquire(registry, "c2", "src/schema.py", "agent_b", SECOND)
        assert not outcome.granted
        assert outcome.claim is None
        assert outcome.holder is not None
        assert outcome.holder.agent_id == "agent_a"

    def test_only_one_of_many_contenders_succeeds(self, registry: ClaimRegistry) -> None:
        results = [
            acquire(registry, f"c{i}", "src/schema.py", f"agent_{i}", i) for i in range(6)
        ]
        assert sum(1 for r in results if r.granted) == 1

    def test_different_paths_do_not_block_each_other(self, registry: ClaimRegistry) -> None:
        assert acquire(registry, "c1", "src/schema.py", "agent_a", 0).granted
        assert acquire(registry, "c2", "src/api.py", "agent_b", 0).granted

    def test_different_runs_do_not_block_each_other(self, registry: ClaimRegistry) -> None:
        # Arms must not interfere (§2): two runs sharing a database file must
        # not contend for the same logical path.
        assert acquire(registry, "c1", "src/schema.py", "agent_a", 0, run="run_001").granted
        assert acquire(registry, "c2", "src/schema.py", "agent_a", 0, run="run_002").granted

    def test_the_holder_may_reacquire_its_own_claim(self, registry: ClaimRegistry) -> None:
        # An agent asking for a lease it already holds is not a conflict;
        # counting it as one would inflate the blocked-write rate.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        outcome = acquire(registry, "c1b", "src/schema.py", "agent_a", SECOND)
        assert outcome.granted
        assert outcome.claim is not None
        assert outcome.claim.claim_id == "c1"
        assert outcome.claim.renewals == 1

    def test_a_reused_claim_id_is_rejected(self, registry: ClaimRegistry) -> None:
        # Duplicate ids would make two leases indistinguishable in the log (§42).
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        with pytest.raises(ClaimError, match="already exists"):
            acquire(registry, "c1", "src/api.py", "agent_b", SECOND)


class TestPathNormalization:
    def test_backslash_and_forward_slash_are_the_same_resource(
        self, registry: ClaimRegistry
    ) -> None:
        # Without this, the exclusivity invariant would silently not hold
        # between agents on different platforms.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        assert not acquire(registry, "c2", "src\\schema.py", "agent_b", SECOND).granted

    def test_surrounding_whitespace_is_ignored(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        assert not acquire(registry, "c2", "  src/schema.py  ", "agent_b", SECOND).granted

    @pytest.mark.parametrize("bad", ["", "   "], ids=["empty", "whitespace"])
    def test_an_empty_path_is_rejected(self, registry: ClaimRegistry, bad: str) -> None:
        with pytest.raises(ClaimError, match="non-empty"):
            acquire(registry, "c1", bad, "agent_a", 0)


class TestExpiry:
    """§21: leases lapse, and a lapsed lease must stop blocking."""

    def test_an_expired_claim_stops_blocking(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        assert acquire(registry, "c2", "src/schema.py", "agent_b", 20 * SECOND).granted

    def test_expiry_is_exclusive_at_the_deadline(self, registry: ClaimRegistry) -> None:
        # A claim expiring exactly now is already free; the boundary is
        # pinned so lease-wait measurements are not off by one instant.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        assert registry.check(path="src/schema.py", run_id=RUN, now_us=10 * SECOND - 1) is not None
        assert registry.check(path="src/schema.py", run_id=RUN, now_us=10 * SECOND) is None

    def test_expiry_needs_no_sweep(self, registry: ClaimRegistry) -> None:
        # Correctness must not depend on background maintenance running.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        assert registry.may_write(
            path="src/schema.py", agent_id="agent_b", run_id=RUN, now_us=99 * SECOND
        ).granted

    def test_the_sweep_records_the_transition(self, registry: ClaimRegistry) -> None:
        # Expiries must be countable in the metrics, so the state change is
        # persisted even though correctness does not depend on it.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        assert registry.expire(run_id=RUN, now_us=20 * SECOND) == 1
        assert registry.history(run_id=RUN)[0].status == ClaimStatus.EXPIRED

    def test_the_sweep_leaves_live_claims_alone(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=100 * SECOND)
        assert registry.expire(run_id=RUN, now_us=50 * SECOND) == 0

    def test_a_crashed_holder_is_taken_over_after_the_lease_lapses(
        self, registry: ClaimRegistry
    ) -> None:
        """§21 crash recovery: an agent that dies must not hold a path forever."""
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=LEASE)
        # agent_a never renews and never releases — it is gone.
        takeover = acquire(registry, "c2", "src/schema.py", "agent_b", LEASE + 1)
        assert takeover.granted
        assert takeover.claim is not None
        assert takeover.claim.agent_id == "agent_b"


class TestRenewal:
    def test_renewal_extends_the_deadline(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        outcome = registry.renew(
            claim_id="c1", agent_id="agent_a", now_us=5 * SECOND, duration_us=10 * SECOND
        )
        assert outcome.granted
        assert outcome.claim is not None
        assert outcome.claim.expires_at_us == 15 * SECOND
        assert outcome.claim.renewals == 1

    def test_renewal_keeps_the_path_blocked(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        registry.renew(claim_id="c1", agent_id="agent_a", now_us=5 * SECOND, duration_us=100 * SECOND)
        assert not acquire(registry, "c2", "src/schema.py", "agent_b", 50 * SECOND).granted

    def test_an_expired_claim_cannot_be_renewed(self, registry: ClaimRegistry) -> None:
        """Otherwise a crashed agent could reclaim a path someone else took over."""
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, duration=10 * SECOND)
        outcome = registry.renew(
            claim_id="c1", agent_id="agent_a", now_us=20 * SECOND, duration_us=10 * SECOND
        )
        assert not outcome.granted
        assert "expired" in outcome.reason

    def test_another_agent_cannot_renew_someone_elses_claim(
        self, registry: ClaimRegistry
    ) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        outcome = registry.renew(
            claim_id="c1", agent_id="agent_b", now_us=SECOND, duration_us=LEASE
        )
        assert not outcome.granted
        assert "belongs to" in outcome.reason

    def test_renewing_an_unknown_claim_is_reported(self, registry: ClaimRegistry) -> None:
        outcome = registry.renew(
            claim_id="nope", agent_id="agent_a", now_us=0, duration_us=LEASE
        )
        assert not outcome.granted
        assert "no such claim" in outcome.reason


class TestRelease:
    def test_release_frees_the_path_immediately(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        assert registry.release(claim_id="c1", agent_id="agent_a", now_us=SECOND).granted
        assert acquire(registry, "c2", "src/schema.py", "agent_b", 2 * SECOND).granted

    def test_release_is_idempotent(self, registry: ClaimRegistry) -> None:
        # §42: a duplicated operation must not become an error.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        registry.release(claim_id="c1", agent_id="agent_a", now_us=SECOND)
        assert registry.release(claim_id="c1", agent_id="agent_a", now_us=2 * SECOND).granted

    def test_another_agent_cannot_release_someone_elses_claim(
        self, registry: ClaimRegistry
    ) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        outcome = registry.release(claim_id="c1", agent_id="agent_b", now_us=SECOND)
        assert not outcome.granted
        assert registry.check(path="src/schema.py", run_id=RUN, now_us=2 * SECOND) is not None

    def test_released_and_expired_are_distinguishable(self, registry: ClaimRegistry) -> None:
        # Collapsing them would erase an orderly finish from a timeout in the
        # measurements (§21).
        acquire(registry, "c1", "src/a.py", "agent_a", 0, duration=10 * SECOND)
        acquire(registry, "c2", "src/b.py", "agent_a", 0, duration=10 * SECOND)
        registry.release(claim_id="c1", agent_id="agent_a", now_us=SECOND)
        registry.expire(run_id=RUN, now_us=50 * SECOND)

        by_id = {c.claim_id: c for c in registry.history(run_id=RUN)}
        assert by_id["c1"].status == ClaimStatus.RELEASED
        assert by_id["c2"].status == ClaimStatus.EXPIRED


class TestWriteGate:
    """`may_write` is the C3 gate consulted before every write."""

    def test_an_unclaimed_path_is_writable(self, registry: ClaimRegistry) -> None:
        # Claims are exclusive when held, not mandatory before every write.
        assert registry.may_write(
            path="src/schema.py", agent_id="agent_a", run_id=RUN, now_us=0
        ).granted

    def test_the_holder_may_write(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        assert registry.may_write(
            path="src/schema.py", agent_id="agent_a", run_id=RUN, now_us=SECOND
        ).granted

    def test_a_non_holder_is_denied(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        outcome = registry.may_write(
            path="src/schema.py", agent_id="agent_b", run_id=RUN, now_us=SECOND
        )
        assert not outcome.granted
        assert outcome.holder is not None
        assert "denied" in outcome.reason

    def test_the_gate_does_not_mutate_state(self, registry: ClaimRegistry) -> None:
        # The gate is consulted constantly; if it recorded denials itself the
        # counts would depend on how often it was called.
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        for _ in range(5):
            registry.may_write(path="src/schema.py", agent_id="agent_b", run_id=RUN, now_us=SECOND)
        assert registry.denials(run_id=RUN) == []


class TestDenialRecords:
    """§20: every blocked write must be recorded with its full context."""

    def test_a_denial_records_who_was_blocked_by_whom(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        acquire(registry, "c2", "src/schema.py", "agent_b", SECOND)

        denials = registry.denials(run_id=RUN)
        assert len(denials) == 1
        assert denials[0]["requesting_agent"] == "agent_b"
        assert denials[0]["holder_agent"] == "agent_a"
        assert denials[0]["holder_claim_id"] == "c1"
        assert denials[0]["path"] == "src/schema.py"
        assert denials[0]["timestamp_us"] == SECOND

    def test_denials_accumulate(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        for i in range(3):
            acquire(registry, f"cx{i}", "src/schema.py", "agent_b", (i + 1) * SECOND)
        assert len(registry.denials(run_id=RUN)) == 3

    def test_a_successful_acquisition_records_no_denial(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0)
        assert registry.denials(run_id=RUN) == []

    def test_denials_are_scoped_per_run(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/schema.py", "agent_a", 0, run="run_001")
        acquire(registry, "c2", "src/schema.py", "agent_b", SECOND, run="run_001")
        assert len(registry.denials(run_id="run_001")) == 1
        assert registry.denials(run_id="run_002") == []


class TestHistory:
    def test_history_retains_every_claim(self, registry: ClaimRegistry) -> None:
        acquire(registry, "c1", "src/a.py", "agent_a", 0, duration=10 * SECOND)
        registry.release(claim_id="c1", agent_id="agent_a", now_us=SECOND)
        acquire(registry, "c2", "src/a.py", "agent_b", 2 * SECOND)
        assert [c.claim_id for c in registry.history(run_id=RUN)] == ["c1", "c2"]

    def test_active_claims_excludes_expired_and_released(
        self, registry: ClaimRegistry
    ) -> None:
        acquire(registry, "c1", "src/a.py", "agent_a", 0, duration=10 * SECOND)
        acquire(registry, "c2", "src/b.py", "agent_a", 0, duration=100 * SECOND)
        acquire(registry, "c3", "src/c.py", "agent_a", 0, duration=100 * SECOND)
        registry.release(claim_id="c3", agent_id="agent_a", now_us=SECOND)

        active = registry.active_claims(run_id=RUN, now_us=50 * SECOND)
        assert [c.claim_id for c in active] == ["c2"]


class TestPersistence:
    def test_claims_survive_reopening_the_database(self, tmp_path: Path) -> None:
        """State must outlive the process: agents run as separate processes."""
        database = tmp_path / "claims.db"
        with ClaimRegistry(database) as first:
            acquire(first, "c1", "src/schema.py", "agent_a", 0)

        with ClaimRegistry(database) as second:
            holder = second.check(path="src/schema.py", run_id=RUN, now_us=SECOND)
            assert holder is not None
            assert holder.agent_id == "agent_a"
            assert not acquire(second, "c2", "src/schema.py", "agent_b", SECOND).granted

    def test_denials_survive_reopening(self, tmp_path: Path) -> None:
        database = tmp_path / "claims.db"
        with ClaimRegistry(database) as first:
            acquire(first, "c1", "src/schema.py", "agent_a", 0)
            acquire(first, "c2", "src/schema.py", "agent_b", SECOND)
        with ClaimRegistry(database) as second:
            assert len(second.denials(run_id=RUN)) == 1

    def test_the_parent_directory_is_created(self, tmp_path: Path) -> None:
        with ClaimRegistry(tmp_path / "nested" / "dir" / "claims.db") as registry:
            assert acquire(registry, "c1", "src/a.py", "agent_a", 0).granted


class TestClaimValue:
    def test_validity_depends_on_status_and_time(self) -> None:
        claim = Claim(
            claim_id="c1",
            path="src/a.py",
            agent_id="agent_a",
            run_id=RUN,
            issued_at_us=0,
            expires_at_us=10 * SECOND,
        )
        assert claim.is_valid_at(5 * SECOND)
        assert not claim.is_valid_at(10 * SECOND)

    def test_a_released_claim_is_never_valid(self) -> None:
        claim = Claim(
            claim_id="c1",
            path="src/a.py",
            agent_id="agent_a",
            run_id=RUN,
            issued_at_us=0,
            expires_at_us=10 * SECOND,
            status=ClaimStatus.RELEASED,
        )
        assert not claim.is_valid_at(SECOND)

    def test_invalid_durations_are_rejected(self, registry: ClaimRegistry) -> None:
        for duration in (0, -1):
            with pytest.raises(ClaimError, match="positive"):
                acquire(registry, "c1", "src/a.py", "agent_a", 0, duration=duration)
