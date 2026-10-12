from __future__ import annotations

import math

import pytest

from causalmesh.analysis import inference as inf
from causalmesh.analysis.inference import (
    InferenceError,
    equivalence_by_interval,
    fisher_exact,
    holm_bonferroni,
    n_per_arm_for_power,
    newcombe_difference,
    power_two_proportions,
    tally_outcomes,
    wilson_interval,
)

pytestmark = pytest.mark.unit


class TestWilson:
    def test_eight_of_ten_at_95(self) -> None:
        # z = 1.959964, z^2 = 3.84146, n = 10, p = 0.8.
        # denom  = 1 + z^2/n               = 1.384146
        # centre = (0.8 + z^2/20) / denom  = 0.992073 / 1.384146 = 0.716746
        # half   = z/denom * sqrt(0.16/10 + z^2/400)
        #        = 1.416045 * sqrt(0.016 + 0.009604) = 1.416045 * 0.160013 = 0.226590
        # interval = (0.716746 - 0.226590, 0.716746 + 0.226590) = (0.4902, 0.9433)
        result = wilson_interval(8, 10, confidence=0.95)
        low, high = result
        assert low == pytest.approx(0.4902, abs=1e-4)
        assert high == pytest.approx(0.9433, abs=1e-4)
        assert result.estimate == 0.8

    def test_zero_successes_has_exact_lower_bound_zero(self) -> None:
        # p = 0: centre = half = z^2/(2n) / (1 + z^2/n), so low is exactly 0.
        result = wilson_interval(0, 10, confidence=0.95)
        assert result.low == 0.0
        # high = 2 * centre = z^2/n / (1 + z^2/n) = 0.384146 / 1.384146 = 0.2775
        assert result.high == pytest.approx(0.2775, abs=1e-4)

    def test_all_successes_has_exact_upper_bound_one(self) -> None:
        # By symmetry with 0 of 10: (1 - 0.2775, 1) = (0.7225, 1).
        result = wilson_interval(10, 10, confidence=0.95)
        assert result.high == 1.0
        assert result.low == pytest.approx(0.7225, abs=1e-4)

    def test_higher_confidence_is_wider(self) -> None:
        narrow = wilson_interval(8, 10, confidence=0.90)
        wide = wilson_interval(8, 10, confidence=0.99)
        assert wide.low < narrow.low and wide.high > narrow.high

    def test_to_dict_states_what_it_was_computed_from(self) -> None:
        payload = wilson_interval(8, 10, confidence=0.95).to_dict()
        assert payload["successes"] == 8 and payload["n"] == 10
        assert payload["confidence"] == 0.95 and payload["method"] == "wilson"


class TestNewcombe:
    def test_newcombe_1998_worked_example(self) -> None:
        # Newcombe (1998), Table II, 56/70 against 48/80, 95% method 10.
        # Treatment Wilson (z^2 = 3.84146, n = 70, p = 0.8):
        #   centre 0.784412, half 0.092520 -> (0.69189, 0.87693)
        # Baseline Wilson (n = 80, p = 0.6):
        #   centre 0.595417, half 0.104967 -> (0.49045, 0.70038)
        # d    = 0.8 - 0.6 = 0.2
        # low  = d - sqrt((0.8 - 0.69189)^2 + (0.70038 - 0.6)^2)
        #      = 0.2 - sqrt(0.011688 + 0.010076) = 0.2 - 0.14753 = 0.0525
        # high = d + sqrt((0.87693 - 0.8)^2 + (0.6 - 0.49045)^2)
        #      = 0.2 + sqrt(0.005919 + 0.012000) = 0.2 + 0.13386 = 0.3339
        result = newcombe_difference(56, 70, 48, 80, confidence=0.95)
        assert result.difference == pytest.approx(0.2)
        assert result.low == pytest.approx(0.0524, abs=5e-4)
        assert result.high == pytest.approx(0.3339, abs=5e-4)

    def test_direction_is_treatment_minus_baseline(self) -> None:
        # Swapping the arms negates the difference and mirrors the interval.
        forward = newcombe_difference(56, 70, 48, 80, confidence=0.95)
        backward = newcombe_difference(48, 80, 56, 70, confidence=0.95)
        assert backward.difference == pytest.approx(-forward.difference)
        assert backward.low == pytest.approx(-forward.high)
        assert backward.high == pytest.approx(-forward.low)

    def test_interval_stays_inside_minus_one_and_one(self) -> None:
        extreme = newcombe_difference(10, 10, 0, 10, confidence=0.95)
        assert -1.0 <= extreme.low <= extreme.difference <= extreme.high <= 1.0


class TestFisher:
    def test_three_one_one_three(self) -> None:
        # Margins 4, 4, 4, 4; n = 8; x = cell a ranges 0..4.
        # P(x) = C(4,x) C(4,4-x) / C(8,4) = 1, 16, 36, 16, 1 over 70.
        # Observed x = 3 has 16; the tables no more probable are x = 0, 1, 3, 4:
        # p = (1 + 16 + 16 + 1) / 70 = 34/70 = 0.485714
        assert fisher_exact(3, 1, 1, 3).p_value == pytest.approx(34 / 70)

    def test_a_table_with_p_exactly_one(self) -> None:
        # [[1,1],[1,1]]: P(x) = 1, 4, 1 over 6; observed x = 1 is the mode,
        # so every table is no more probable: p = 6/6 = 1.
        assert fisher_exact(1, 1, 1, 1).p_value == 1.0

    def test_an_extreme_table(self) -> None:
        # [[10,0],[0,10]]: P(x = 10) = 1 / C(20,10) = 1/184756; the mirror
        # table x = 0 is equally improbable and nothing else is that rare:
        # p = 2 / 184756 = 1.0825e-5
        assert fisher_exact(10, 0, 0, 10).p_value == pytest.approx(2 / 184756)

    def test_a_degenerate_margin_gives_one(self) -> None:
        # An empty row leaves a single possible table, with probability 1.
        assert fisher_exact(0, 0, 3, 4).p_value == 1.0

    def test_the_other_orientation_of_an_extreme_table(self) -> None:
        assert fisher_exact(0, 10, 10, 0).p_value == pytest.approx(2 / 184756)


class TestHolm:
    def test_worked_example(self) -> None:
        # Ascending: 0.01, 0.03, 0.04 with multipliers 3, 2, 1:
        #   0.01 * 3 = 0.03; 0.03 * 2 = 0.06; 0.04 * 1 = 0.04 -> max so far 0.06.
        # Back in input order [0.01, 0.04, 0.03]: [0.03, 0.06, 0.06].
        # At alpha = 0.05 only 0.03 <= 0.05 is rejected.
        result = holm_bonferroni([0.01, 0.04, 0.03], alpha=0.05)
        assert result.adjusted == pytest.approx((0.03, 0.06, 0.06))
        assert result.reject == (True, False, False)

    def test_input_order_is_preserved(self) -> None:
        # Descending input: ascending sort gives 0.001*4, 0.01*3, 0.02*2, 0.5*1
        # = 0.004, 0.03, 0.04, 0.5, reported against the original positions.
        result = holm_bonferroni([0.5, 0.02, 0.01, 0.001], alpha=0.05)
        assert result.adjusted == pytest.approx((0.5, 0.04, 0.03, 0.004))
        assert result.reject == (False, True, True, True)

    def test_adjusted_values_are_capped_at_one(self) -> None:
        # 3 * 0.6 = 1.8 and 2 * 0.7 = 1.4 both cap at 1.
        result = holm_bonferroni([0.6, 0.7, 0.9], alpha=0.05)
        assert result.adjusted == (1.0, 1.0, 1.0)

    def test_step_down_stops_at_the_first_non_rejection(self) -> None:
        # Sorted 0.02, 0.021, 0.5 -> 0.06, 0.042 -> monotone 0.06, 0.5.
        # 0.021 has a smaller raw value than 0.06 would suggest, but is held
        # at 0.06 by monotonicity, so neither is rejected at 0.05.
        result = holm_bonferroni([0.02, 0.021, 0.5], alpha=0.05)
        assert result.adjusted == pytest.approx((0.06, 0.06, 0.5))
        assert result.reject == (False, False, False)

    def test_a_single_hypothesis_is_unadjusted(self) -> None:
        assert holm_bonferroni([0.04], alpha=0.05).adjusted == (0.04,)


class TestEquivalence:
    def test_interval_inside_the_margin_is_equivalent(self) -> None:
        result = equivalence_by_interval(-0.05, 0.06, margin=0.10, alpha=0.05)
        assert result.equivalent is True
        assert result.interval_confidence == pytest.approx(0.90)

    def test_straddling_zero_but_wider_than_margin_is_not_equivalent(self) -> None:
        # Not significantly different from zero, and not equivalent either.
        result = equivalence_by_interval(-0.15, 0.12, margin=0.10, alpha=0.05)
        assert result.equivalent is False

    def test_entirely_beyond_the_margin_is_not_equivalent(self) -> None:
        assert equivalence_by_interval(0.12, 0.30, margin=0.10, alpha=0.05).equivalent is False

    def test_an_interval_touching_the_margin_is_not_equivalent(self) -> None:
        # "Strictly inside": the margin itself is not excluded.
        assert equivalence_by_interval(-0.10, 0.05, margin=0.10, alpha=0.05).equivalent is False

    def test_a_non_significant_difference_with_a_wide_interval_is_not_equivalent(self) -> None:
        # 12/30 against 10/30: the difference is not significant, and the
        # 90% interval is far wider than a +/-0.10 margin.
        interval = newcombe_difference(12, 30, 10, 30, confidence=1 - 2 * 0.05)
        assert interval.low < 0.0 < interval.high
        assert interval.high - interval.low > 0.20
        assert fisher_exact(12, 18, 10, 20).p_value > 0.05
        result = equivalence_by_interval(interval.low, interval.high, margin=0.10, alpha=0.05)
        assert result.equivalent is False
        assert "not shown equivalent" in result.statement

    def test_the_docstring_states_that_non_significance_is_not_equivalence(self) -> None:
        doc = " ".join((equivalence_by_interval.__doc__ or "").split())
        assert "non-significant difference is not an equivalence result" in doc


class TestPower:
    def test_power_is_monotone_in_n(self) -> None:
        powers = [
            power_two_proportions(0.5, 0.7, n, alpha=0.05).power for n in (10, 20, 40, 80, 160)
        ]
        assert powers == sorted(powers) and len(set(powers)) == len(powers)

    def test_power_is_about_half_where_the_effect_equals_the_critical_value(self) -> None:
        # Power is Phi((|d| sqrt(n) - z sd0) / sd1) + a negligible far tail,
        # so it is 0.5 where |d| sqrt(n) = z sd0, i.e.
        #   n* = z^2 * 2 pbar (1 - pbar) / d^2
        #      = 3.84146 * 0.48 / 0.04 = 46.10     (p0 = 0.5, p1 = 0.7)
        # n is an integer, so check it straddles 0.5 and is close to it.
        below = power_two_proportions(0.5, 0.7, 46, alpha=0.05).power
        above = power_two_proportions(0.5, 0.7, 47, alpha=0.05).power
        assert below < 0.5 < above
        assert below == pytest.approx(0.5, abs=0.01)
        assert above == pytest.approx(0.5, abs=0.01)

    def test_zero_effect_has_power_equal_to_alpha(self) -> None:
        # With no effect the rejection probability is the test's size.
        assert power_two_proportions(0.4, 0.4, 50, alpha=0.05).power == pytest.approx(0.05)

    def test_it_is_symmetric_in_the_direction_of_the_effect(self) -> None:
        up = power_two_proportions(0.4, 0.6, 50, alpha=0.05).power
        down = power_two_proportions(0.6, 0.4, 50, alpha=0.05).power
        assert up == pytest.approx(down)

    def test_the_result_states_its_assumptions(self) -> None:
        result = power_two_proportions(0.5, 0.7, 93, alpha=0.05)
        payload = result.to_dict()
        assert payload["alpha"] == 0.05
        assert payload["p_baseline"] == 0.5 and payload["p_treatment"] == 0.7
        assert payload["n_per_arm"] == 93
        assert "two-proportion z-test" in payload["formula"]

    def test_sample_size_for_eighty_percent_power(self) -> None:
        # z_a = 1.959964, z_b = 0.841621, sd0 = sqrt(2 * 0.6 * 0.4) = 0.69282,
        # sd1 = sqrt(0.25 + 0.21) = 0.67823:
        #   n = (1.959964 * 0.69282 + 0.841621 * 0.67823)^2 / 0.2^2
        #     = (1.35790 + 0.57082)^2 / 0.04 = 3.71958 / 0.04 = 92.99 -> 93
        result = n_per_arm_for_power(0.5, 0.7, alpha=0.05, power=0.80)
        assert result.n_per_arm == 93
        assert result.achieved_power >= 0.80
        assert power_two_proportions(0.5, 0.7, 92, alpha=0.05).power < 0.80
        assert result.to_dict()["target_power"] == 0.80
        assert result.p_baseline == 0.5 and result.alpha == 0.05

    def test_no_sample_size_detects_a_zero_effect(self) -> None:
        with pytest.raises(InferenceError):
            n_per_arm_for_power(0.5, 0.5, alpha=0.05, power=0.8)


class TestUnknownOutcomes:
    def test_unknown_is_excluded_and_counted(self) -> None:
        tally = tally_outcomes([True, False, None, True, None, None])
        assert (tally.successes, tally.failures, tally.unknown) == (2, 1, 3)
        # The denominator an inference function should be given:
        assert tally.n_known == 3
        assert tally.n_total == 6

    def test_unknown_is_never_a_failure(self) -> None:
        tally = tally_outcomes([None, None])
        assert tally.failures == 0 and tally.n_known == 0
        # Nothing known, so nothing to infer from: refuse rather than report 0.
        with pytest.raises(InferenceError):
            wilson_interval(tally.successes, tally.n_known, confidence=0.95)

    def test_a_non_boolean_outcome_is_refused(self) -> None:
        with pytest.raises(InferenceError):
            tally_outcomes([True, 1])  # type: ignore[list-item]


class TestValidation:
    @pytest.mark.parametrize(
        ("successes", "n"),
        [(0, 0), (11, 10), (-1, 10), (5, -2), (1.5, 10), (True, 10), ("3", 10)],
    )
    def test_wilson_rejects_bad_counts(self, successes: object, n: object) -> None:
        with pytest.raises(InferenceError):
            wilson_interval(successes, n, confidence=0.95)  # type: ignore[arg-type]

    @pytest.mark.parametrize("confidence", [0.0, 1.0, -0.1, 1.5, math.nan, math.inf, True, "0.95"])
    def test_confidence_must_be_strictly_inside_zero_and_one(self, confidence: object) -> None:
        with pytest.raises(InferenceError):
            wilson_interval(8, 10, confidence=confidence)  # type: ignore[arg-type]

    @pytest.mark.parametrize("alpha", [0.0, 1.0, -0.05, 2.0, math.nan])
    def test_alpha_must_be_strictly_inside_zero_and_one(self, alpha: float) -> None:
        with pytest.raises(InferenceError):
            holm_bonferroni([0.01], alpha=alpha)
        with pytest.raises(InferenceError):
            power_two_proportions(0.4, 0.6, 50, alpha=alpha)

    def test_newcombe_rejects_an_empty_arm(self) -> None:
        with pytest.raises(InferenceError):
            newcombe_difference(0, 0, 3, 10, confidence=0.95)
        with pytest.raises(InferenceError):
            newcombe_difference(3, 10, 0, 0, confidence=0.95)

    def test_newcombe_rejects_successes_above_n(self) -> None:
        with pytest.raises(InferenceError):
            newcombe_difference(11, 10, 3, 10, confidence=0.95)

    @pytest.mark.parametrize("table", [(-1, 1, 1, 1), (0, 0, 0, 0), (1.5, 1, 1, 1)])
    def test_fisher_rejects_bad_tables(self, table: tuple) -> None:
        with pytest.raises(InferenceError):
            fisher_exact(*table)

    @pytest.mark.parametrize("pvalues", [[], [1.2], [-0.1], [math.nan]])
    def test_holm_rejects_bad_pvalues(self, pvalues: list[float]) -> None:
        with pytest.raises(InferenceError):
            holm_bonferroni(pvalues, alpha=0.05)

    def test_equivalence_rejects_bad_arguments(self) -> None:
        with pytest.raises(InferenceError):
            equivalence_by_interval(0.1, -0.1, margin=0.1, alpha=0.05)  # low > high
        with pytest.raises(InferenceError):
            equivalence_by_interval(-0.1, 0.1, margin=0.0, alpha=0.05)
        with pytest.raises(InferenceError):
            equivalence_by_interval(-0.1, 0.1, margin=-0.1, alpha=0.05)
        with pytest.raises(InferenceError):
            equivalence_by_interval(-0.1, 0.1, margin=0.1, alpha=0.5)  # 1 - 2*alpha = 0

    @pytest.mark.parametrize(("p0", "p1"), [(0.0, 0.5), (0.5, 1.0), (1.5, 0.5), (0.5, -0.1)])
    def test_power_rejects_proportions_outside_the_open_interval(
        self, p0: float, p1: float
    ) -> None:
        with pytest.raises(InferenceError):
            power_two_proportions(p0, p1, 50, alpha=0.05)

    def test_power_rejects_a_bad_n(self) -> None:
        for bad in (0, -5, 10.5):
            with pytest.raises(InferenceError):
                power_two_proportions(0.4, 0.6, bad, alpha=0.05)  # type: ignore[arg-type]

    def test_the_error_is_a_value_error(self) -> None:
        assert issubclass(InferenceError, ValueError)

    def test_the_assumptions_are_required_keyword_arguments(self) -> None:
        # No default for alpha, confidence, margin or power: a caller must
        # state each, because none has been preregistered.
        with pytest.raises(TypeError):
            wilson_interval(8, 10)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            newcombe_difference(5, 10, 4, 10)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            holm_bonferroni([0.01, 0.02])  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            equivalence_by_interval(-0.1, 0.1, margin=0.1)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            equivalence_by_interval(-0.1, 0.1, alpha=0.05)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            power_two_proportions(0.5, 0.6, 50)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            n_per_arm_for_power(0.5, 0.6, alpha=0.05)  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            wilson_interval(8, 10, 0.95)  # type: ignore[misc]

    def test_nothing_in_the_module_defaults_an_assumption(self) -> None:
        import inspect

        for name in inf.__all__:
            member = getattr(inf, name)
            if not callable(member) or not inspect.isfunction(member):
                continue
            for parameter in inspect.signature(member).parameters.values():
                if parameter.name in {"alpha", "confidence", "margin", "power"}:
                    assert parameter.default is inspect.Parameter.empty, (name, parameter.name)


class TestProperties:
    def test_fisher_p_is_in_zero_one_and_symmetric_under_row_swap(self) -> None:
        checked = 0
        for a in range(7):
            for b in range(7):
                for c in range(7):
                    for d in range(7):
                        if a + b + c + d == 0:
                            continue
                        p = fisher_exact(a, b, c, d).p_value
                        assert 0.0 < p <= 1.0, (a, b, c, d, p)
                        swapped = fisher_exact(c, d, a, b).p_value
                        assert swapped == pytest.approx(p), (a, b, c, d)
                        # Column swap is the same table read the other way.
                        assert fisher_exact(b, a, d, c).p_value == pytest.approx(p)
                        checked += 1
        assert checked == 7**4 - 1

    def test_wilson_is_inside_the_unit_interval_and_contains_the_estimate(self) -> None:
        for confidence in (0.5, 0.8, 0.9, 0.95, 0.99):
            for n in range(1, 31):
                for s in range(n + 1):
                    r = wilson_interval(s, n, confidence=confidence)
                    assert 0.0 <= r.low <= r.estimate <= r.high <= 1.0, (s, n, confidence)

    def test_newcombe_contains_the_difference_and_stays_in_range(self) -> None:
        for nt in (1, 5, 12):
            for nb in (1, 7, 12):
                for st in range(nt + 1):
                    for sb in range(nb + 1):
                        r = newcombe_difference(st, nt, sb, nb, confidence=0.95)
                        assert -1.0 <= r.low <= r.difference <= r.high <= 1.0
