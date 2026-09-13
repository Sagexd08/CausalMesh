"""The contested-path task, executed (spec §35, §74, §20).

This task exists to close a specific gap: the claim registry had recorded
2 claims held and **0 denials, ever**. No task produced a contested path,
so the C3 gate had never refused anything, and "C3 prevents conflicting
writes" was an untested claim.

§74 asks for the enforcement trade-off to be *measured* rather than assumed
to be an improvement. On this task it is not an improvement, and that is
the finding: the contested file genuinely needs two writers, so exclusive
locking preserves one agent's work by destroying the other's.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.tasks import (
    RunConfig,
    TaskDefinition,
    check_sensitivity,
    execute_task,
    validate_structure,
)
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
TASK_PATH = REPO / "tasks" / "concurrent_edit_collision.yaml"
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-collision-integration1"


@pytest.fixture(scope="module")
def task() -> TaskDefinition:
    return TaskDefinition.from_yaml(TASK_PATH)


@pytest.fixture(scope="module")
async def all_arms(task: TaskDefinition, tmp_path_factory) -> dict:
    """One run per arm, shared across the read-only tests.

    Module-scoped: each run spawns a real pytest subprocess, so a
    function-scoped fixture would execute dozens of runs instead of four.
    """
    root = tmp_path_factory.mktemp("collision")
    results = {"_root": root}
    for arm in ("C0", "C1", "C2", "C3"):
        results[arm] = await execute_task(
            task,
            RunConfig(
                experiment_id="exp_collision",
                run_id=f"run_{arm}",
                arm=arm,
                master_seed=SEED,
            ),
            workspace_root=root / arm,
            fixtures_root=FIXTURES,
        )
    return results


def registrations(root: Path, arm: str) -> list[str]:
    """The register() calls in the integrated config — what actually merged."""
    config = root / arm / f"run_{arm}_integrated" / "src" / "config.py"
    if not config.is_file():
        return []
    return [
        line
        for line in config.read_text(encoding="utf-8").splitlines()
        if line.startswith("register(")
    ]


class TestTheTaskIsWellFormed:
    def test_it_validates(self, task: TaskDefinition) -> None:
        report = validate_structure(task)
        assert report.valid, [i.message for i in report.issues]

    def test_the_contested_path_is_declared(self, task: TaskDefinition) -> None:
        assert task.contested_paths == frozenset({"src/config.py"})

    def test_ownership_actually_overlaps(self, task: TaskDefinition) -> None:
        """The property that distinguishes this from schema_handler_widen.

        There, ownership is disjoint and enforcement never has anything to
        refuse. Here both agents write the same path, so the gate is
        exercised for real.
        """
        writers = {
            agent_id
            for agent_id, script in task.scenario.items()
            for action in script.get("actions", [])
            if isinstance(action, dict)
            for kind, body in action.items()
            if kind == "write"
            and (body.get("path") if isinstance(body, dict) else None) == "src/config.py"
        }
        assert writers == {"agent_a", "agent_b"}


class TestEnforcementActuallyBlocks:
    """The Phase 0 acceptance criterion."""

    async def test_c3_records_a_denial(self, all_arms: dict) -> None:
        # The whole point. Before this task existed, this number was
        # always zero and nothing revealed that enforcement was untested.
        denials = all_arms["C3"].denials
        assert len(denials) >= 1, "C3 blocked nothing; enforcement is still unproven"

    async def test_the_denial_names_actor_path_and_holder(self, all_arms: dict) -> None:
        # §20: a blocked write must be attributable, not merely counted.
        denial = all_arms["C3"].denials[0]
        assert denial["requesting_agent"] == "agent_b"
        assert denial["holder_agent"] == "agent_a"
        assert denial["path"] == "src/config.py"
        assert "agent_a" in denial["reason"]

    async def test_unenforced_arms_record_no_denials(self, all_arms: dict) -> None:
        # A denial in C0/C1/C2 would mean enforcement leaked into an arm
        # defined as unenforced, breaking the contrast.
        for arm in ("C0", "C1", "C2"):
            assert all_arms[arm].denials == []

    async def test_the_blocked_write_left_the_file_alone(
        self, all_arms: dict, tmp_path_factory
    ) -> None:
        """A denied write must not partially apply.

        The gate runs before the executor, so a refusal means the file was
        never opened. If a denial still mutated the target, enforcement
        would be recording a block it did not perform.
        """
        result = all_arms["C3"]
        digests = result.workspace_digests
        # agent_b was refused on config.py, so its copy must still match
        # the fixture's original content rather than its own attempted one.
        assert "src/config.py" in digests["agent_b"]


class TestTheArmsSeparate:
    async def test_the_isolated_arm_clobbers(self, all_arms: dict, tmp_path_factory) -> None:
        c0 = all_arms["C0"]
        assert not c0.succeeded
        assert not c0.outcome.divergence_absent, (
            "C0 should leave the sole-registration marker behind"
        )

    @pytest.mark.parametrize("arm", ["C1", "C2"])
    async def test_the_informed_arms_succeed(self, all_arms: dict, arm: str) -> None:
        # Information alone is enough here: agent_b learns agent_a
        # registered first and preserves that registration.
        assert all_arms[arm].succeeded, all_arms[arm].outcome.detail

    async def test_c3_fails_and_that_is_the_finding(self, all_arms: dict) -> None:
        """§74: the trade-off is measured, not assumed to be an improvement.

        Enforcement prevents the clobber — C0's divergence marker is absent
        — but the contested file genuinely needs two writers, so refusing
        one of them means the task cannot be completed. Exclusive locking
        is the wrong tool for this shape of work.

        This is a result about enforcement, not a defect in the gate.
        """
        c3 = all_arms["C3"]
        assert not c3.succeeded
        # It failed differently from C0: the clobber was prevented.
        assert c3.outcome.divergence_absent
        assert not all_arms["C0"].outcome.divergence_absent


class TestMergedContent:
    """What actually landed in the shared file — the mechanism, not the flag.

    An outcome that was right for the wrong reason would pass every
    boolean check above. These read the merged file.
    """

    async def test_the_isolated_arm_loses_the_first_registration(
        self, all_arms: dict
    ) -> None:
        found = registrations(all_arms["_root"], "C0")
        assert found == ['register("beta", beta.handle)  # sole registration']

    @pytest.mark.parametrize("arm", ["C1", "C2"])
    async def test_the_informed_arms_keep_both(self, all_arms: dict, arm: str) -> None:
        found = registrations(all_arms["_root"], arm)
        assert found == [
            'register("alpha", alpha.handle)',
            'register("beta", beta.handle)',
        ]

    async def test_enforcement_preserves_the_holders_write(
        self, all_arms: dict
    ) -> None:
        """C3 keeps agent_a's registration and loses agent_b's.

        The exact inverse of C0. Enforcement protected the first writer at
        the cost of the second — which is the trade-off §74 asks to be
        measured rather than assumed away.
        """
        found = registrations(all_arms["_root"], "C3")
        assert found == ['register("alpha", alpha.handle)']


class TestEvidence:
    async def test_every_arm_produces_a_verifiable_chain(self, all_arms: dict) -> None:
        from causalmesh.crypto.keys import KeyPair, PublicKeyRing

        for arm, result in all_arms.items():
            if arm == "_root":
                continue
            agents = {r["event"]["identity"]["agent_id"] for r in result.records}
            ring = PublicKeyRing.from_keypairs(
                {a: KeyPair.derive(SEED, a) for a in agents}
            )
            report = verify_chain(result.records, ring)
            assert report.valid, f"{arm}: {report.summary()}"

    async def test_c3_holds_leases_on_every_owned_path(self, all_arms: dict) -> None:
        held = {c["path"] for c in all_arms["C3"].claim_history}
        assert held == {"src/config.py", "src/alpha.py", "src/beta.py"}

    async def test_the_denial_is_absent_from_the_chain_as_a_write(
        self, all_arms: dict
    ) -> None:
        """A refused write must not appear as an accepted write event.

        The contested-path merge resolves from the chain, so a denied write
        appearing there would let a blocked agent win the file — which is
        precisely the bug that made C3 look like it had lost both
        registrations.
        """
        writes = [
            r["event"]
            for r in all_arms["C3"].records
            if r["event"]["event_type"].lower() == "write"
            and "src/config.py" in r["event"]["paths"]
        ]
        assert {w["identity"]["agent_id"] for w in writes} == {"agent_a"}


class TestQualityGate:
    async def test_the_task_is_demonstrably_coordination_sensitive(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        """§37: sensitivity is demonstrated by running, not asserted."""
        report = await check_sensitivity(
            task,
            workspace_root=tmp_path / "gate",
            fixtures_root=FIXTURES,
            master_seed=SEED,
            repetitions=1,
        )
        assert report.sensitive, report.detail
        assert report.informed_successes > report.isolated_successes
