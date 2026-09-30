"""The scaled task, the scaling metrics and the scalability profile (spec §86).

The claims pinned here:

- the scaled task is well-formed, deterministic and generated from its
  parameters alone, at every size;
- the growth exponent says what it claims and is `None` when undefined;
- an absent measurement is reported as unknown, never as zero;
- the profile is described, not gated, and outside the run-planning registry.
"""

from __future__ import annotations

import pytest

from causalmesh.experiments import ProfileError, profile, scalability as design
from causalmesh.experiments.scalability import (
    SCALABILITY_PROFILES,
    ScalabilityProfile,
    scalability_profile,
)
from causalmesh.metrics import ScalingRun, growth_exponent, summarize_scaling
from causalmesh.relay import BROADCAST, DELIVERY_MODES, PATH_SCOPED
from causalmesh.tasks import TaskError, validate_structure
from causalmesh.tasks.scaled import (
    MAX_SCALED_AGENTS,
    ScaledSpec,
    generate_scaled_task,
    scaled_fixture_files,
)

pytestmark = pytest.mark.unit


class TestScaledTask:
    @pytest.mark.parametrize(
        ("n_agents", "group_size"), [(2, 2), (4, 4), (8, 4), (9, 4), (16, 4), (16, 16), (32, 4)]
    )
    def test_the_generated_task_is_valid_at_every_size(
        self, n_agents: int, group_size: int
    ) -> None:
        spec = ScaledSpec(n_agents=n_agents, group_size=group_size)
        task = generate_scaled_task(spec)
        report = validate_structure(task)
        assert report.valid, [issue.to_dict() for issue in report.errors]
        assert len(task.agent_ids) == n_agents

    def test_it_is_deterministic_and_its_hash_moves_with_the_parameters(self) -> None:
        a = generate_scaled_task(ScaledSpec(8))
        assert a.content_hash() == generate_scaled_task(ScaledSpec(8)).content_hash()
        assert a.content_hash() != generate_scaled_task(ScaledSpec(9)).content_hash()
        assert a.content_hash() != generate_scaled_task(ScaledSpec(8, group_size=8)).content_hash()
        assert a.content_hash() != generate_scaled_task(ScaledSpec(8, own_files=3)).content_hash()

    def test_each_agent_owns_its_own_directory_and_nobody_else_does(self) -> None:
        spec = ScaledSpec(n_agents=8, group_size=4, own_files=3)
        task = generate_scaled_task(spec)
        for index, role in enumerate(task.roles):
            own_dir = f"src/pkg_{index:02d}/"
            in_dir = {p for p in role.owns if p.startswith(own_dir)}
            assert len(in_dir) == 3
            for other in task.roles:
                if other is not role:
                    assert not any(p.startswith(own_dir) for p in other.owns | other.depends_on)

    def test_contention_groups_share_exactly_one_path_each(self) -> None:
        spec = ScaledSpec(n_agents=10, group_size=4)
        task = generate_scaled_task(spec)
        assert spec.groups == 3
        assert task.contested_paths == frozenset(spec.shared_path(g) for g in range(3))
        # Exactly one owner per shared path: the first member. The rest depend on it.
        for group in range(3):
            shared = spec.shared_path(group)
            owners = [r.agent_id for r in task.roles if shared in r.owns]
            dependents = [r.agent_id for r in task.roles if shared in r.depends_on]
            members = list(spec.members(group))
            assert owners == members[:1]
            assert dependents == members[1:]

    def test_a_trailing_group_of_one_contests_nothing(self) -> None:
        spec = ScaledSpec(n_agents=9, group_size=4)
        task = generate_scaled_task(spec)
        assert spec.shared_path(2) not in task.contested_paths

    def test_dense_puts_every_agent_in_one_group(self) -> None:
        spec = ScaledSpec(n_agents=16, group_size=16)
        assert spec.groups == 1
        assert len(spec.members(0)) == 16

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"n_agents": 1},
            {"n_agents": MAX_SCALED_AGENTS + 1},
            {"n_agents": 4, "group_size": 1},
            {"n_agents": 4, "group_size": 5},
            {"n_agents": 4, "own_files": 0},
        ],
    )
    def test_invalid_parameters_are_refused(self, kwargs: dict) -> None:
        with pytest.raises(TaskError):
            ScaledSpec(**kwargs)

    def test_the_fixture_matches_the_task_and_is_ascii_lf(self) -> None:
        spec = ScaledSpec(n_agents=8, group_size=4)
        files = scaled_fixture_files(spec)
        task = generate_scaled_task(spec)
        declared = {p for r in task.roles for p in r.owns | r.depends_on}
        assert declared <= set(files), "a declared path is missing from the fixture"
        assert "tests/check_scaled.py" in files
        for text in files.values():
            text.encode("ascii")
            assert "\r" not in text


def scaling_run(n: int, **overrides) -> ScalingRun:
    values = {
        "n_agents": n,
        "arm": "C2",
        "delivery_mode": BROADCAST,
        "topology": "localized",
        "group_size": 4,
        "agent_events": 6 * n,
        "events_available": 6 * n * (n - 1),
        "events_delivered": 6 * n * (n - 1),
        "events_injected": 6 * n * (n - 1),
        "coordination_bytes": 100 * n,
        "per_agent_bytes": (100,) * n,
        "per_agent_delivered": (6 * (n - 1),) * n,
        "succeeded": True,
        "chain_valid": True,
        "head_hash": "h",
    }
    values.update(overrides)
    return ScalingRun(**values)


class TestGrowthExponent:
    def test_linear_is_one_and_quadratic_is_two(self) -> None:
        assert growth_exponent([(2, 10), (4, 20), (8, 40)]) == pytest.approx(1.0)
        assert growth_exponent([(2, 4), (4, 16), (8, 64)]) == pytest.approx(2.0)

    def test_constant_cost_is_exponent_zero_not_unknown(self) -> None:
        assert growth_exponent([(2, 5), (4, 5), (8, 5)]) == pytest.approx(0.0)

    def test_it_is_none_when_undefined_rather_than_zero(self) -> None:
        assert growth_exponent([]) is None
        assert growth_exponent([(4, 10)]) is None
        assert growth_exponent([(4, 10), (4, 20)]) is None  # one distinct N
        assert growth_exponent([(4, 0), (8, 10)]) is None  # log of zero

    def test_series_group_by_arm_topology_and_mode_in_a_stable_order(self) -> None:
        runs = [
            scaling_run(16),
            scaling_run(4, delivery_mode=PATH_SCOPED),
            scaling_run(4),
            scaling_run(8),
            scaling_run(8, delivery_mode=PATH_SCOPED),
        ]
        series = summarize_scaling(runs)
        assert [(s.delivery_mode, [r.n_agents for r in s.runs]) for s in series] == [
            (BROADCAST, [16, 4, 8]),
            (PATH_SCOPED, [4, 8]),
        ]
        assert series[0].to_dict()["runs"][0]["n_agents"] == 4  # sorted in the report


class TestScalingRunReporting:
    def test_an_absent_injection_count_is_unknown_not_zero(self) -> None:
        run = scaling_run(4, events_injected=None)
        assert run.events_unseen is None
        assert run.to_dict()["events_unseen"] is None

    def test_unseen_is_delivered_minus_injected(self) -> None:
        run = scaling_run(4, events_delivered=72, events_injected=60)
        assert run.events_unseen == 12

    def test_delivery_ratio_is_unknown_when_nothing_was_available(self) -> None:
        assert scaling_run(4, events_available=0, events_delivered=0).delivery_ratio is None
        assert scaling_run(4, events_available=72, events_delivered=24).delivery_ratio == (
            pytest.approx(1 / 3)
        )

    def test_an_unknown_outcome_stays_unknown(self) -> None:
        assert scaling_run(4, succeeded=None).to_dict()["succeeded"] is None


class TestScalabilityProfile:
    def test_the_design_module_spells_the_modes_as_the_relay_does(self) -> None:
        assert design.DELIVERY_MODES == DELIVERY_MODES
        assert (design.BROADCAST, design.PATH_SCOPED) == (BROADCAST, PATH_SCOPED)

    def test_asking_the_run_planner_for_scalability_points_at_the_right_command(self) -> None:
        with pytest.raises(ProfileError, match="experiment scalability"):
            profile("scalability")

    def test_the_named_profiles_exist_and_are_not_gated(self) -> None:
        assert set(SCALABILITY_PROFILES) == {"scalability", "scalability_smoke"}
        for found in SCALABILITY_PROFILES.values():
            assert found.gated is False

    def test_the_full_profile_spans_beyond_four_agents(self) -> None:
        found = scalability_profile("scalability")
        assert found.agent_counts == (4, 8, 16)
        # 3 sizes x 2 modes x 2 arms x 2 topologies
        assert found.run_count() == 24

    def test_the_smoke_profile_is_small(self) -> None:
        assert scalability_profile("scalability_smoke").run_count() == 4

    def test_an_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown scalability profile"):
            scalability_profile("enormous")

    def test_a_profile_needs_two_sizes_and_a_broadcast_baseline_and_no_c0(self) -> None:
        with pytest.raises(ValueError, match="two agent counts"):
            ScalabilityProfile(name="x", agent_counts=(4,))
        with pytest.raises(ValueError, match="baseline"):
            ScalabilityProfile(name="x", agent_counts=(4, 8), delivery_modes=(PATH_SCOPED,))
        with pytest.raises(ValueError, match="C0"):
            ScalabilityProfile(name="x", agent_counts=(4, 8), arms=("C0",))
        with pytest.raises(ValueError, match="topologies"):
            ScalabilityProfile(name="x", agent_counts=(4, 8), topologies=("ring",))
