"""Claim enforcement against real files (spec §20, §74).

The unit tests check that the gate *returns* a denial. This module checks the
consequence that actually matters: a denied write leaves the artifact
untouched. A gate that reported a denial while the write happened anyway
would satisfy every unit test and invalidate the entire C3 arm.

Files are compared by SHA-256 rather than by content string, because the
claim is byte-level identity, not equality of what someone remembered to
read back.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from causalmesh.claims import ClaimRegistry

pytestmark = pytest.mark.integration

SECOND = 1_000_000
RUN = "run_001"
LEASE = 120 * SECOND
ORIGINAL = "# original content by agent_a\n"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def guarded_write(
    registry: ClaimRegistry, target: Path, content: str, agent: str, now_us: int
) -> bool:
    """Write only if the claim gate allows it — the C3 write path.

    This mirrors what the tool layer does when it is given a registry
    (`Gate._rule_claim`, `src/causalmesh/policy/gate.py:373-397`): consult
    the gate, and perform the write only on a grant. This helper calls
    `ClaimRegistry.may_write` directly and does not go through `Gate`, so it
    tests the decision and the file consequence, not the wiring; the gate's
    claim rule is covered by `TestClaims` in `tests/unit/test_policy.py`.
    The check happens *before* the file is opened, so a denial cannot
    truncate the target as a side effect.
    """
    if not registry.may_write(path=target.name, agent_id=agent, run_id=RUN, now_us=now_us).granted:
        return False
    target.write_text(content, encoding="utf-8")
    return True


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    target = tmp_path / "schema.py"
    target.write_text(ORIGINAL, encoding="utf-8")
    return tmp_path


@pytest.fixture
def registry(tmp_path: Path) -> ClaimRegistry:
    with ClaimRegistry(tmp_path / "claims.db") as reg:
        yield reg


class TestDeniedWrites:
    def test_a_denied_write_leaves_the_file_byte_identical(
        self, workspace: Path, registry: ClaimRegistry
    ) -> None:
        """§20: denied writes never modify the artifact."""
        target = workspace / "schema.py"
        before = digest(target)

        registry.acquire(
            claim_id="c_a",
            path="schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=0,
            duration_us=LEASE,
        )
        wrote = guarded_write(registry, target, "# OVERWRITTEN\n", "agent_b", SECOND)

        assert wrote is False
        assert digest(target) == before
        assert target.read_text(encoding="utf-8") == ORIGINAL

    def test_repeated_denied_attempts_never_touch_the_file(
        self, workspace: Path, registry: ClaimRegistry
    ) -> None:
        target = workspace / "schema.py"
        before = digest(target)
        registry.acquire(
            claim_id="c_a",
            path="schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=0,
            duration_us=LEASE,
        )

        for attempt in range(5):
            assert not guarded_write(
                registry, target, f"# attempt {attempt}\n", "agent_b", (attempt + 1) * SECOND
            )
        assert digest(target) == before

    def test_the_holder_can_still_write(self, workspace: Path, registry: ClaimRegistry) -> None:
        # Enforcement must block conflicting writers, not all writers.
        target = workspace / "schema.py"
        registry.acquire(
            claim_id="c_a",
            path="schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=0,
            duration_us=LEASE,
        )
        assert guarded_write(registry, target, "# updated by holder\n", "agent_a", SECOND)
        assert target.read_text(encoding="utf-8") == "# updated by holder\n"

    def test_an_unclaimed_file_is_writable(self, workspace: Path, registry: ClaimRegistry) -> None:
        target = workspace / "schema.py"
        assert guarded_write(registry, target, "# written freely\n", "agent_b", 0)


class TestArmContrast:
    """§74: the C2/C3 difference, observed rather than assumed."""

    def test_c2_permits_the_conflicting_write_and_c3_prevents_it(self, tmp_path: Path) -> None:
        """The same collision under both arms, on real files.

        C2 has the information channel but no gate, so the write lands and
        the earlier work is lost. C3 consults the gate and the file survives.
        This is the mechanism behind the contrast; whether preventing the
        write improves overall task success is a separate question the
        experiment measures rather than assumes.
        """
        c2_file = tmp_path / "c2_schema.py"
        c3_file = tmp_path / "c3_schema.py"
        for target in (c2_file, c3_file):
            target.write_text(ORIGINAL, encoding="utf-8")

        with ClaimRegistry(tmp_path / "claims.db") as registry:
            # Both arms: agent_a is working on the file and holds a claim.
            # Only C3 consults it.
            registry.acquire(
                claim_id="c_a",
                path="c3_schema.py",
                agent_id="agent_a",
                run_id=RUN,
                now_us=0,
                duration_us=LEASE,
            )

            # C2: no gate in the write path at all.
            c2_file.write_text("# OVERWRITTEN by agent_b\n", encoding="utf-8")

            # C3: gate consulted.
            c3_wrote = guarded_write(
                registry, c3_file, "# OVERWRITTEN by agent_b\n", "agent_b", SECOND
            )

        assert c2_file.read_text(encoding="utf-8") == "# OVERWRITTEN by agent_b\n"
        assert c3_wrote is False
        assert c3_file.read_text(encoding="utf-8") == ORIGINAL

    def test_the_denial_is_recorded_for_measurement(
        self, workspace: Path, registry: ClaimRegistry
    ) -> None:
        # A prevented conflict that leaves no record cannot be counted, and
        # the C3 arm's cost would be invisible in the analysis.
        target = workspace / "schema.py"
        registry.acquire(
            claim_id="c_a",
            path="schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=0,
            duration_us=LEASE,
        )
        guarded_write(registry, target, "# OVERWRITTEN\n", "agent_b", SECOND)
        # The gate itself is read-only; the attempt is recorded when the agent
        # tries to take the claim it needs.
        registry.acquire(
            claim_id="c_b",
            path="schema.py",
            agent_id="agent_b",
            run_id=RUN,
            now_us=SECOND,
            duration_us=LEASE,
        )

        denials = registry.denials(run_id=RUN)
        assert len(denials) == 1
        assert denials[0]["requesting_agent"] == "agent_b"
        assert denials[0]["holder_agent"] == "agent_a"


class TestLeaseHandover:
    def test_the_path_becomes_writable_after_the_lease_expires(
        self, workspace: Path, registry: ClaimRegistry
    ) -> None:
        """§21: a crashed holder must not block a path forever."""
        target = workspace / "schema.py"
        registry.acquire(
            claim_id="c_a",
            path="schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=0,
            duration_us=LEASE,
        )
        assert not guarded_write(registry, target, "# too early\n", "agent_b", SECOND)
        assert guarded_write(registry, target, "# after handover\n", "agent_b", LEASE + 1)
        assert target.read_text(encoding="utf-8") == "# after handover\n"

    def test_release_hands_over_immediately(self, workspace: Path, registry: ClaimRegistry) -> None:
        target = workspace / "schema.py"
        registry.acquire(
            claim_id="c_a",
            path="schema.py",
            agent_id="agent_a",
            run_id=RUN,
            now_us=0,
            duration_us=LEASE,
        )
        registry.release(claim_id="c_a", agent_id="agent_a", now_us=SECOND)
        assert guarded_write(registry, target, "# after release\n", "agent_b", 2 * SECOND)
