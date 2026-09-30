"""The interface_consumer and shared_utility_refactor tasks, executed (spec §35, §37).

These are the two families §35 named that stayed unbuilt while the gate was
proven on one task. Both are *dependency-shaped*, like `schema_handler_widen`
and unlike `concurrent_edit_collision`: ownership is disjoint, nothing is
contested, and one agent's write can invalidate the other's work.

What is pinned here is a measurement, not a hope. The §37 gate was run for
real on each task and the verdicts below are what it returned. They are
expected to be SENSITIVE, and the reason is worth stating plainly: the
dependency exists by construction. The fixture's change is breaking (no
default argument, no alias), and the consumer's script branches on whether
it was told about the change. The gate confirms that this construction does
what it was built to do. It does not show that a real model would act on
the information; every run uses a deterministic mock agent.

The harness runs `python -m pytest` as a subprocess, so these tests need a
`python` on PATH that has pytest installed. Where it does not, every arm
fails identically, the gate reports NOT SENSITIVE, and the reason is the
environment rather than the task. See docs/backlog.md, "Remaining task families".
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import pytest

from causalmesh.crypto.keys import KeyPair, PublicKeyRing
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
FIXTURES = REPO / "fixtures"
SEED = b"causalmesh-task-families-seed001"
ARMS = ("C0", "C1", "C2", "C3")


@dataclass(frozen=True)
class Family:
    """What differs between the two tasks; everything else is shared."""

    task_id: str
    provider_path: str
    consumer_path: str
    stale_marker: str


FAMILIES = {
    "interface_consumer": Family(
        task_id="interface_consumer",
        provider_path="src/pricing.py",
        consumer_path="src/cart.py",
        stale_marker="pricing.quote(item)",
    ),
    "shared_utility_refactor": Family(
        task_id="shared_utility_refactor",
        provider_path="src/textutil.py",
        consumer_path="src/tags.py",
        stale_marker="textutil.slugify(",
    ),
}


# Backward-compatible provider rewrites: (text to replace, replacement).
COMPATIBLE_PROVIDERS = {
    "interface_consumer": (
        "def quote(item, region):",
        "def quote(item, region=DEFAULT_REGION):",
    ),
    "shared_utility_refactor": (
        '    return re.sub(r"[^a-z0-9]+", sep, text.lower()).strip(sep)\n',
        '    return re.sub(r"[^a-z0-9]+", sep, text.lower()).strip(sep)\n\n\nslugify = make_slug\n',
    ),
}


@pytest.fixture(scope="module", params=sorted(FAMILIES))
def family(request) -> Family:
    return FAMILIES[request.param]


@pytest.fixture(scope="module")
def task(family: Family) -> TaskDefinition:
    return TaskDefinition.from_yaml(REPO / "tasks" / f"{family.task_id}.yaml")


@pytest.fixture(scope="module")
async def all_arms(task: TaskDefinition, tmp_path_factory) -> dict:
    """One run per arm, shared across the read-only tests.

    Module-scoped: each run spawns a real pytest subprocess, so a
    function-scoped fixture would execute dozens of runs instead of four.
    """
    root = tmp_path_factory.mktemp(task.task_id)
    results = {"_root": root}
    for arm in ARMS:
        results[arm] = await execute_task(
            task,
            RunConfig(
                experiment_id=f"exp_{task.task_id}",
                run_id=f"run_{arm}",
                arm=arm,
                master_seed=SEED,
            ),
            workspace_root=root / arm,
            fixtures_root=FIXTURES,
        )
    return results


def integrated(all_arms: dict, arm: str, relative: str) -> str:
    path = all_arms["_root"] / arm / f"run_{arm}_integrated" / relative
    return path.read_text(encoding="utf-8") if path.is_file() else ""


class TestTheTaskIsWellFormed:
    def test_it_validates_with_no_issues(self, task: TaskDefinition) -> None:
        report = validate_structure(task, fixtures_root=FIXTURES)
        assert report.valid, [i.detail for i in report.issues]
        assert report.issues == []

    def test_nothing_is_contested(self, task: TaskDefinition) -> None:
        # Dependency-shaped, not contention-shaped: enforcement has nothing
        # legitimate to refuse here.
        assert task.contested_paths == frozenset()


class TestTheArmsSeparate:
    """Which arms succeed, measured over all four."""

    async def test_the_isolated_arm_fails_on_both_criteria(self, all_arms: dict) -> None:
        c0 = all_arms["C0"]
        assert not c0.succeeded
        assert not c0.outcome.tests_passed
        assert not c0.outcome.divergence_absent

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    async def test_every_informed_arm_succeeds(self, all_arms: dict, arm: str) -> None:
        assert all_arms[arm].succeeded, all_arms[arm].outcome.detail

    async def test_the_difference_comes_from_being_informed(
        self, all_arms: dict, family: Family
    ) -> None:
        # The mechanism, not only the outcome.
        assert all_arms["C0"].agent_summaries["agent_b"]["informed_paths"] == []
        for arm in ("C1", "C2", "C3"):
            informed = all_arms[arm].agent_summaries["agent_b"]["informed_paths"]
            assert family.provider_path in informed

    async def test_the_uninformed_agent_records_why_it_did_not_act(
        self, all_arms: dict, family: Family
    ) -> None:
        skipped = all_arms["C0"].agent_summaries["agent_b"]["skipped_actions"]
        assert any(f"not informed about {family.provider_path}" in s["reason"] for s in skipped)


class TestTheFailureIsTheIntendedOne:
    """C0 must fail because of the stale call shape, not for some other reason.

    An outcome that was right for the wrong reason would pass every boolean
    check above, so these read the merged file and the marker.
    """

    async def test_the_stale_call_shape_is_what_survives_in_c0(
        self, all_arms: dict, family: Family
    ) -> None:
        assert family.stale_marker in integrated(all_arms, "C0", family.consumer_path)
        assert all_arms["C0"].outcome.divergence_found_in == family.consumer_path

    @pytest.mark.parametrize("arm", ["C1", "C2", "C3"])
    async def test_the_informed_arms_use_the_current_shape(
        self, all_arms: dict, family: Family, arm: str
    ) -> None:
        assert family.stale_marker not in integrated(all_arms, arm, family.consumer_path)

    async def test_the_provider_change_lands_in_every_arm(
        self, all_arms: dict, family: Family
    ) -> None:
        # The provider is identical across arms, so the contrast is about
        # the consumer and nothing else.
        provider = {integrated(all_arms, arm, family.provider_path) for arm in ARMS}
        assert len(provider) == 1
        assert provider != {""}


class TestEnforcement:
    async def test_c3_holds_a_lease_on_every_owned_path(
        self, all_arms: dict, task: TaskDefinition
    ) -> None:
        owned = {path for role in task.roles for path in role.owns}
        assert {c["path"] for c in all_arms["C3"].claim_history} == owned

    async def test_c3_blocks_nothing_because_ownership_is_disjoint(self, all_arms: dict) -> None:
        # §74: prevention is measured, not assumed to help. Here it never has
        # anything to refuse, so C3 costs nothing and gains nothing over C2.
        assert all_arms["C3"].denials == []

    async def test_unenforced_arms_hold_no_claims(self, all_arms: dict) -> None:
        for arm in ("C0", "C1", "C2"):
            assert all_arms[arm].claim_history == []


class TestCoordinationCost:
    async def test_the_isolated_arm_spends_nothing(self, all_arms: dict) -> None:
        assert all_arms["C0"].coordination_bytes() == 0

    async def test_c2_and_c3_spend_the_same(self, all_arms: dict) -> None:
        assert all_arms["C2"].coordination_bytes() > 0
        assert all_arms["C2"].coordination_bytes() == all_arms["C3"].coordination_bytes()


class TestEvidence:
    async def test_every_arm_produces_a_verifiable_chain(self, all_arms: dict) -> None:
        for arm in ARMS:
            result = all_arms[arm]
            agents = {r["event"]["identity"]["agent_id"] for r in result.records}
            ring = PublicKeyRing.from_keypairs({a: KeyPair.derive(SEED, a) for a in agents})
            report = verify_chain(result.records, ring)
            assert report.valid, f"{arm}: {report.summary()}"

    async def test_every_run_records_the_task_hash(
        self, all_arms: dict, task: TaskDefinition
    ) -> None:
        for arm in ARMS:
            assert all_arms[arm].task_hash == task.content_hash()


class TestQualityGate:
    """§37, run for real. The verdict is reported, not tuned."""

    async def test_the_verdict_is_sensitive_with_the_real_counts(
        self, task: TaskDefinition, tmp_path: Path
    ) -> None:
        report = await check_sensitivity(
            task,
            workspace_root=tmp_path / "gate",
            fixtures_root=FIXTURES,
            master_seed=SEED,
            repetitions=1,
        )
        assert report.sensitive, report.detail
        assert (report.isolated_successes, report.informed_successes) == (0, 1)
        assert (report.isolated_divergences, report.informed_divergences) == (1, 0)


class TestTheDependencyIsTheBreakingChange:
    """What the fixture's breaking change is worth, measured by removing it.

    The provider is rebuilt backward-compatibly (a default argument, or a
    deprecated alias) and the uninformed consumer is run again. Its stale
    call shape now WORKS, so the integration tests pass, and the run still
    fails: the §38 rule requires the divergence marker to be absent as well,
    and the marker is a string check on the stale call shape.

    That is a finding about the gate, not a defect to fix here. On these
    tasks the verdict is carried jointly by the breaking change and by the
    marker; the marker alone would flag a harmless stale call as a failure.
    """

    async def test_a_compatible_provider_lets_the_stale_shape_pass_the_tests(
        self, task: TaskDefinition, family: Family, tmp_path: Path
    ) -> None:
        old, new = COMPATIBLE_PROVIDERS[family.task_id]
        data = copy.deepcopy(task.to_dict())
        actions = data["scenario"]["agent_a"]["actions"]
        rewritten = 0
        for action in actions:
            body = action.get("write") if isinstance(action, dict) else None
            if isinstance(body, dict) and body["path"] == family.provider_path:
                assert old in body["content"]
                body["content"] = body["content"].replace(old, new)
                rewritten += 1
        assert rewritten == 1
        compatible = TaskDefinition.from_dict(data)

        result = await execute_task(
            compatible,
            RunConfig(
                experiment_id="exp_ablation",
                run_id="run_C0",
                arm="C0",
                master_seed=SEED,
            ),
            workspace_root=tmp_path / "C0",
            fixtures_root=FIXTURES,
        )
        assert result.outcome.tests_passed, result.outcome.detail
        assert not result.outcome.divergence_absent
        assert not result.succeeded
