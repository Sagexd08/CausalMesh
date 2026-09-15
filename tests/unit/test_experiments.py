"""Unit tests for the experimental design (spec §2, §39 to §41).

The design is the experiment. These tests check the properties the analysis
will later depend on — that arms differ in exactly the declared factors,
that a plan is balanced, and that randomization is derived rather than
sampled — because a defect here does not crash anything, it silently
produces a different experiment from the one described.
"""

from __future__ import annotations

import pytest

from causalmesh.experiments import (
    ARM_IDS,
    ARMS,
    PRIMARY_CONTRASTS,
    Enforcement,
    Information,
    Profile,
    ProfileError,
    arm,
    contrast,
    derive_run_seed,
    plan_experiment,
    profile,
    shuffled,
)

pytestmark = pytest.mark.unit

SEED = b"causalmesh-experiments-unit-seed"


class TestArms:
    def test_the_four_arms_exist(self) -> None:
        assert set(ARMS) == {"C0", "C1", "C2", "C3"}

    def test_an_unknown_arm_raises_rather_than_defaulting(self) -> None:
        # A typo silently resolving to C0 would produce runs labelled as one
        # condition and executed as another — the worst error available.
        with pytest.raises(ValueError, match="unknown arm"):
            arm("C4")

    def test_c2_and_c3_differ_only_in_enforcement(self) -> None:
        """The contrast the project exists to measure.

        If these two arms ever differed in their information factor, the
        C2→C3 comparison would confound enforcement with information and
        the central result would be uninterpretable.
        """
        c2, c3 = arm("C2"), arm("C3")
        assert c2.information == c3.information
        assert c2.enforcement != c3.enforcement

    def test_c1_and_c2_differ_only_in_information(self) -> None:
        c1, c2 = arm("C1"), arm("C2")
        assert c1.enforcement == c2.enforcement == Enforcement.NONE
        assert c1.information != c2.information

    def test_c0_is_the_only_uninformed_arm(self) -> None:
        uninformed = [a for a in ARMS.values() if not a.is_informed]
        assert [a.arm_id for a in uninformed] == ["C0"]

    def test_c3_is_the_only_enforced_arm(self) -> None:
        enforced = [a for a in ARMS.values() if a.is_enforced]
        assert [a.arm_id for a in enforced] == ["C3"]

    def test_every_factor_level_is_one_of_the_declared_levels(self) -> None:
        levels = {Information.NONE, Information.TRANSCRIPT, Information.METADATA}
        for a in ARMS.values():
            assert a.information in levels
            assert a.enforcement in {Enforcement.NONE, Enforcement.CLAIMS}


class TestContrasts:
    def test_each_primary_contrast_names_real_arms(self) -> None:
        for item in PRIMARY_CONTRASTS:
            assert item.baseline in ARM_IDS
            assert item.treatment in ARM_IDS

    def test_the_single_factor_contrasts_really_vary_one_factor(self) -> None:
        """§4: a contrast claiming to isolate a factor must actually do so.

        This is a property of the *design*, checkable from the arm table
        alone, and asserting it here means a future edit to an arm cannot
        quietly invalidate a contrast's interpretation.
        """
        single = {"information_benefit", "representation", "enforcement_benefit"}
        for item in PRIMARY_CONTRASTS:
            if item.name not in single:
                continue
            baseline, treatment = arm(item.baseline), arm(item.treatment)
            differing = sum(
                [
                    baseline.information != treatment.information,
                    baseline.enforcement != treatment.enforcement,
                ]
            )
            assert differing == 1, f"{item.name} varies {differing} factors, not 1"

    def test_the_complete_system_contrast_is_declared_confounded(self) -> None:
        # C1 vs C3 varies both factors. That is intentional, and the
        # rationale must say so rather than letting a reader assume it
        # isolates something.
        item = contrast("complete_system")
        baseline, treatment = arm(item.baseline), arm(item.treatment)
        assert baseline.information != treatment.information
        assert baseline.enforcement != treatment.enforcement
        assert "confounded" in item.rationale.lower()

    def test_an_unknown_contrast_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown contrast"):
            contrast("information_and_vibes")


class TestProfiles:
    def test_the_confirmatory_profile_is_gated(self) -> None:
        """§77: the machinery exists, the gate stays closed."""
        with pytest.raises(ProfileError, match="gated"):
            profile("confirmatory")

    def test_the_gate_can_be_opened_explicitly(self) -> None:
        found = profile("confirmatory", allow_gated=True)
        assert found.repetitions == 120

    def test_the_gate_reason_explains_itself(self) -> None:
        # An operator who hits the gate must learn why, not just that.
        with pytest.raises(ProfileError) as info:
            profile("confirmatory")
        assert "preregistered" in str(info.value)

    def test_ungated_profiles_need_no_flag(self) -> None:
        for name in ("smoke", "pilot", "small", "medium"):
            assert profile(name).name == name

    def test_an_unknown_profile_raises(self) -> None:
        with pytest.raises(ProfileError, match="unknown profile"):
            profile("enormous")

    def test_the_confirmatory_profile_is_the_1920_run_design(self) -> None:
        # 4 tasks x 4 arms x 120 repetitions, the §48 preregistered scale.
        assert profile("confirmatory", allow_gated=True).run_count(4) == 1920

    def test_smoke_is_capped_to_one_task(self) -> None:
        found = profile("smoke")
        assert found.run_count(4) == 4  # 1 task x 4 arms x 1 repetition


class TestShuffle:
    def test_the_same_seed_gives_the_same_order(self) -> None:
        items = list(range(50))
        assert shuffled(items, SEED, "x") == shuffled(items, SEED, "x")

    def test_a_different_label_gives_a_different_order(self) -> None:
        items = list(range(50))
        assert shuffled(items, SEED, "a") != shuffled(items, SEED, "b")

    def test_a_different_seed_gives_a_different_order(self) -> None:
        items = list(range(50))
        assert shuffled(items, SEED, "x") != shuffled(items, b"another-seed-x", "x")

    def test_it_is_a_permutation(self) -> None:
        items = list(range(200))
        assert sorted(shuffled(items, SEED, "x")) == items

    def test_it_does_not_mutate_its_input(self) -> None:
        items = list(range(20))
        shuffled(items, SEED, "x")
        assert items == list(range(20))

    def test_it_actually_reorders(self) -> None:
        # A "shuffle" that returned its input unchanged would pass every
        # test above. Over 100 items an identity permutation is not a
        # plausible draw.
        items = list(range(100))
        assert shuffled(items, SEED, "x") != items

    def test_the_distribution_is_not_obviously_degenerate(self) -> None:
        """Every element must reach many positions across seeds.

        Not a uniformity proof — that needs a statistical test this suite
        has no business running. It catches the realistic bug: an index
        stream that collapses, so one element always lands in one place.
        """
        positions: dict[int, set[int]] = {i: set() for i in range(10)}
        for trial in range(60):
            order = shuffled(list(range(10)), SEED, f"trial{trial}")
            for index, value in enumerate(order):
                positions[value].add(index)
        for value, seen in positions.items():
            assert len(seen) >= 7, f"element {value} only reached {len(seen)} positions"

    def test_an_empty_seed_is_refused(self) -> None:
        # An unseeded plan cannot be reproduced, so it must not be created.
        with pytest.raises(ValueError, match="master_seed"):
            shuffled([1, 2, 3], b"", "x")


class TestRunSeeds:
    def test_a_run_seed_is_derived_deterministically(self) -> None:
        assert derive_run_seed(SEED, "run_a") == derive_run_seed(SEED, "run_a")

    def test_different_runs_get_different_seeds(self) -> None:
        assert derive_run_seed(SEED, "run_a") != derive_run_seed(SEED, "run_b")

    def test_run_seeds_do_not_collide_with_plan_draws(self) -> None:
        """Namespacing check.

        Plan ordering and run seeds come from the same master seed. If they
        shared a derivation, a run's signing key would be predictable from
        its position in the schedule — not a threat this project models,
        but exactly the kind of coincidence that is hard to spot later.
        """
        from causalmesh.experiments.randomization import _PLAN_INFO, _RUN_SEED_INFO, _derive

        assert _derive(SEED, "x", _PLAN_INFO) != _derive(SEED, "x", _RUN_SEED_INFO)


class TestPlanning:
    def test_the_design_is_fully_crossed(self) -> None:
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        assert len(plan) == 2 * 4 * 3
        assert plan.is_balanced()

    def test_every_cell_holds_the_same_number_of_runs(self) -> None:
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("small"),
            task_ids=["t1", "t2", "t3"],
            master_seed=SEED,
        )
        for task_id in plan.task_ids:
            for arm_id in plan.arms:
                cell = [r for r in plan.runs if r.task_id == task_id and r.arm == arm_id]
                assert len(cell) == 10

    def test_run_ids_are_unique(self) -> None:
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        ids = [r.run_id for r in plan.runs]
        assert len(set(ids)) == len(ids)

    def test_replanning_gives_identical_run_ids(self) -> None:
        """Resume depends on this.

        Run ids are derived from coordinates, not generated. A UUID would
        make every replan a fresh set of runs and defeat resume entirely.
        """
        kwargs = dict(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        first = plan_experiment(**kwargs)
        second = plan_experiment(**kwargs)
        assert [r.run_id for r in first.runs] == [r.run_id for r in second.runs]
        assert first.content_hash() == second.content_hash()

    def test_the_order_is_randomized_not_blocked(self) -> None:
        """§41: arms must not run in blocks.

        Blocked execution would align each arm with a distinct stretch of
        wall-clock time, confounding it with anything that drifts during a
        collection — a warming cache, a filling disk.
        """
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("small"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        arms_in_order = [r.arm for r in plan.runs]
        # Under blocking, every C0 index would precede every C1 index.
        c0 = [i for i, a in enumerate(arms_in_order) if a == "C0"]
        c1 = [i for i, a in enumerate(arms_in_order) if a == "C1"]
        assert max(c0) > min(c1), "C0 runs form a leading block; order is not randomized"

    def test_order_indices_are_dense_and_sequential(self) -> None:
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["t1"],
            master_seed=SEED,
        )
        assert [r.order for r in plan.runs] == list(range(len(plan)))

    def test_a_different_seed_reorders_the_same_runs(self) -> None:
        kwargs = dict(experiment_id="exp", profile=profile("small"), task_ids=["t1", "t2"])
        first = plan_experiment(master_seed=SEED, **kwargs)
        second = plan_experiment(master_seed=b"different-seed-entirely!!", **kwargs)
        assert {r.run_id for r in first.runs} == {r.run_id for r in second.runs}
        assert [r.run_id for r in first.runs] != [r.run_id for r in second.runs]

    def test_the_plan_hash_covers_the_order(self) -> None:
        # Two collections that ran the same runs in different orders are
        # not the same experiment: order is what randomization protects.
        kwargs = dict(experiment_id="exp", profile=profile("small"), task_ids=["t1", "t2"])
        first = plan_experiment(master_seed=SEED, **kwargs)
        second = plan_experiment(master_seed=b"different-seed-entirely!!", **kwargs)
        assert first.content_hash() != second.content_hash()

    def test_smoke_truncates_deterministically(self) -> None:
        # Sorted before truncation, so the subset does not depend on
        # filesystem listing order.
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("smoke"),
            task_ids=["zebra", "alpha", "mango"],
            master_seed=SEED,
        )
        assert plan.task_ids == ("alpha",)
        assert len(plan) == 4

    def test_planning_with_no_tasks_raises(self) -> None:
        with pytest.raises(ValueError, match="no tasks"):
            plan_experiment(
                experiment_id="exp",
                profile=profile("pilot"),
                task_ids=[],
                master_seed=SEED,
            )

    def test_duplicate_task_ids_are_refused(self) -> None:
        with pytest.raises(ValueError, match="duplicate task"):
            plan_experiment(
                experiment_id="exp",
                profile=profile("pilot"),
                task_ids=["t1", "t1"],
                master_seed=SEED,
            )

    def test_a_profile_naming_an_unknown_arm_is_refused_at_plan_time(self) -> None:
        # Failing here rather than part-way through a collection.
        bogus = Profile(name="bogus", repetitions=1, arms=("C0", "C9"))
        with pytest.raises(ValueError, match="unknown arm"):
            plan_experiment(
                experiment_id="exp",
                profile=bogus,
                task_ids=["t1"],
                master_seed=SEED,
            )

    def test_an_unbalanced_plan_is_detected(self) -> None:
        """`is_balanced` must be able to say no.

        A predicate that returned True unconditionally would pass every
        test above, so it is checked against a plan built to be unbalanced.
        """
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("pilot"),
            task_ids=["t1", "t2"],
            master_seed=SEED,
        )
        damaged = plan.runs[:-1]
        object.__setattr__(plan, "runs", damaged)
        assert not plan.is_balanced()

    def test_task_hashes_are_carried_into_the_plan(self) -> None:
        # §33: results can only be pooled across runs of the same task, so
        # the plan pins which task content it was built for.
        plan = plan_experiment(
            experiment_id="exp",
            profile=profile("smoke"),
            task_ids=["t1"],
            master_seed=SEED,
            task_hashes={"t1": "abc123"},
        )
        assert plan.task_hashes == {"t1": "abc123"}
        assert "abc123" in str(plan.to_dict())
