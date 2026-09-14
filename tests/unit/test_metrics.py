"""Coordination-cost accounting and contrasts (spec §44, §45, §46).

The arithmetic is checked against the pilot artifacts on disk rather than
against fixtures invented here. That is deliberate: the value of this layer
is that it agrees with what the channel actually recorded, and a fixture
written to match the code would prove only that the code matches itself.

The pilot figures used below are the published ones (24 runs, C1 361 B,
C2/C3 196 B), so a change that silently altered how cost is aggregated
would fail here rather than quietly restate the project's headline numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from causalmesh.metrics import ArmMetrics, MetricsError, RunMetrics, collect, measure

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / "data" / "raw" / "pilot_landing"


def run(**overrides) -> RunMetrics:
    defaults = dict(
        arm="C2",
        coordination_bytes=196,
        coordination_tokens=51,
        denials=0,
        events=4,
        received_no_coordination=False,
        run_id="r",
        succeeded=True,
        task_id="t",
        turns=8,
    )
    return RunMetrics(**{**defaults, **overrides})


class TestUnknownOutcomes:
    """An absent outcome is not a failure.

    This is the confident-zero defect from docs/backlog.md, in the place it
    would do the most damage: a crashed run counted as a failure inflates
    every failure rate by however many runs crashed before evaluating.
    """

    def test_a_missing_outcome_is_excluded_from_the_rate(self) -> None:
        arm = ArmMetrics(arm="C2", runs=[run(succeeded=True), run(succeeded=None)])
        assert arm.success_rate == 1.0
        assert arm.unknown_outcomes == 1

    def test_a_missing_outcome_is_not_counted_as_a_success(self) -> None:
        arm = ArmMetrics(arm="C2", runs=[run(succeeded=None)])
        assert arm.successes == 0
        assert arm.success_rate is None

    def test_an_empty_arm_has_no_rate_rather_than_zero(self) -> None:
        """A rate over zero runs is not 0.0; reporting it would fabricate."""
        arm = ArmMetrics(arm="C3")
        assert arm.success_rate is None
        assert arm.mean_coordination_bytes is None
        assert arm.bytes_per_turn is None


class TestCostAggregation:
    def test_bytes_per_turn_divides_by_total_turns(self) -> None:
        arm = ArmMetrics(
            arm="C1",
            runs=[run(coordination_bytes=100, turns=4), run(coordination_bytes=300, turns=4)],
        )
        assert arm.mean_coordination_bytes == 200.0
        assert arm.bytes_per_turn == 50.0

    def test_a_run_with_no_turns_cannot_divide_by_zero(self) -> None:
        arm = ArmMetrics(arm="C0", runs=[run(coordination_bytes=0, turns=0)])
        assert arm.bytes_per_turn is None


@pytest.mark.skipif(not PILOT.is_dir(), reason="pilot artifacts are not in this checkout")
class TestAgainstThePilot:
    """The published figures, recomputed from the artifacts that produced them."""

    def test_the_collection_is_balanced_across_four_arms(self) -> None:
        metrics = collect(PILOT)
        assert metrics.run_count == 24
        assert sorted(metrics.arms) == ["C0", "C1", "C2", "C3"]
        assert metrics.is_balanced()

    def test_the_arm_figures_match_the_published_results(self) -> None:
        metrics = collect(PILOT)
        assert metrics.arms["C0"].success_rate == 0.0
        assert metrics.arms["C1"].success_rate == 1.0
        assert metrics.arms["C2"].success_rate == 1.0
        assert metrics.arms["C3"].success_rate == 0.5

        assert metrics.arms["C0"].mean_coordination_bytes == 0.0
        assert metrics.arms["C1"].mean_coordination_bytes == 361.0
        assert metrics.arms["C2"].mean_coordination_bytes == 196.0
        assert metrics.arms["C3"].mean_coordination_bytes == 196.0

    def test_nothing_is_silently_uncounted(self) -> None:
        metrics = collect(PILOT)
        assert all(arm.unknown_outcomes == 0 for arm in metrics.arms.values())

    def test_c0_received_no_coordination_at_all(self) -> None:
        """The C0 assertion is a property of every run, not an average."""
        metrics = collect(PILOT)
        assert all(r.received_no_coordination for r in metrics.arms["C0"].runs)
        assert not any(r.received_no_coordination for r in metrics.arms["C2"].runs)

    def test_only_the_enforcing_arm_denies(self) -> None:
        metrics = collect(PILOT)
        assert metrics.arms["C3"].denials > 0
        assert metrics.arms["C0"].denials == 0
        assert metrics.arms["C1"].denials == 0
        assert metrics.arms["C2"].denials == 0

    def test_c2_and_c3_spend_identically(self) -> None:
        """The enforcement contrast is only clean if the cost is unchanged.

        C2 and C3 carry the same information through the same channel
        object; if their byte totals differed, C2->C3 would be measuring
        information *and* enforcement.
        """
        metrics = collect(PILOT)
        assert (
            metrics.arms["C2"].mean_coordination_bytes
            == metrics.arms["C3"].mean_coordination_bytes
        )


@pytest.mark.skipif(not PILOT.is_dir(), reason="pilot artifacts are not in this checkout")
class TestContrasts:
    def test_information_helps_on_both_tasks(self) -> None:
        metrics = collect(PILOT)
        for task in metrics.task_ids:
            result = next(r for r in measure(metrics, task_id=task) if r.name == "information_benefit")
            assert result.success_delta == 1.0

    def test_bounded_metadata_matches_transcripts_for_less(self) -> None:
        """C1->C2: no loss of success, at 0.543x the coordination cost."""
        metrics = collect(PILOT)
        result = next(r for r in measure(metrics) if r.name == "representation")
        assert result.success_delta == 0.0
        assert result.bytes_ratio == pytest.approx(196 / 361)

    def test_enforcement_differs_by_task(self) -> None:
        """The finding that makes the per-task split necessary (§74).

        Pooling these two produces -0.50, which describes neither task: on
        disjoint ownership enforcement has nothing to block, and on a
        contested path it blocks work that genuinely needed to happen.
        """
        metrics = collect(PILOT)

        disjoint = next(
            r
            for r in measure(metrics, task_id="schema_handler_widen")
            if r.name == "enforcement_benefit"
        )
        contested = next(
            r
            for r in measure(metrics, task_id="concurrent_edit_collision")
            if r.name == "enforcement_benefit"
        )
        assert disjoint.success_delta == 0.0
        assert contested.success_delta == -1.0

    def test_enforcement_changes_no_cost(self) -> None:
        metrics = collect(PILOT)
        result = next(r for r in measure(metrics) if r.name == "enforcement_benefit")
        assert result.bytes_ratio == 1.0

    def test_every_planned_contrast_is_measured(self) -> None:
        metrics = collect(PILOT)
        names = {r.name for r in measure(metrics)}
        assert names == {
            "complete_system",
            "enforcement_benefit",
            "information_benefit",
            "representation",
        }
        assert all(r.measurable for r in measure(metrics))


class TestFailureModes:
    def test_a_missing_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(MetricsError):
            collect(tmp_path / "nope")

    def test_an_empty_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(MetricsError):
            collect(tmp_path)

    def test_unreadable_json_is_refused_rather_than_skipped(self, tmp_path: Path) -> None:
        """A skipped run would change the denominator without saying so."""
        run_dir = tmp_path / "broken__C0__r0000"
        run_dir.mkdir()
        (run_dir / "run.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(MetricsError):
            collect(tmp_path)

    def test_a_run_without_an_outcome_reads_as_unknown(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "x__C2__r0000"
        run_dir.mkdir()
        (run_dir / "run.json").write_text(
            json.dumps({"arm": "C2", "result": {"run_id": "x", "task_id": "t"}}),
            encoding="utf-8",
        )
        metrics = collect(tmp_path)
        assert metrics.arms["C2"].unknown_outcomes == 1
        assert metrics.arms["C2"].success_rate is None
