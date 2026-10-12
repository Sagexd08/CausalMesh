"""Inference primitives: intervals, an exact test, multiplicity, equivalence, power.

**What this is, and is not.** Pure arithmetic over counts a caller supplies,
standard library only (`statistics.NormalDist` for the normal quantile and
cdf, `math.comb` for the exact test). It is the "primitives only" half of
`docs/PLAN.md` Step 13. It is *not* the preregistered analysis:
`docs/preregistration-draft.md` is an unsigned draft whose alpha, interval
level, model, multiplicity handling, equivalence margin and power
assumptions are all still TODO. So:

- no function here carries a default for `alpha`, `confidence` or `margin`;
  a caller states its assumption, in the call, where a reader can see it;
- nothing here is "preregistered" or "confirmatory", and a result computed
  with these functions must not be described as either;
- the mixed-effects logistic model with task random intercepts is not built
  (`docs/backlog.md`). Every function here treats the counts it is given as
  independent Bernoulli trials, which is wrong when runs share a task. The
  caller owns that assumption.

**Unknown outcomes.** An absent outcome is unknown, never a failure
(AGENTS.md). `tally_outcomes` separates the three, and the inference
functions take counts: the caller passes `n = successes + failures` and the
unknown runs are reported beside the result, never inside the denominator.

Every function validates its inputs and raises `InferenceError`
(a `ValueError`) rather than returning a number that merely looks usable.
Results are frozen dataclasses with `to_dict()`, so a report can state which
assumptions produced a figure.

References, each checked against a published worked example in
`tests/unit/test_inference.py`:

- Wilson, E. B. (1927). J. Amer. Statist. Assoc., 22, 209-212.
- Newcombe, R. G. (1998). "Interval estimation for the difference between
  independent proportions: comparison of eleven methods." Statistics in
  Medicine, 17, 873-890. Method 10, the hybrid score interval.
- Fisher's exact test, two-sided by the "sum of tables no more probable than
  the observed one" rule (the rule R's `fisher.test` uses).
- Holm, S. (1979). Scand. J. Statist., 6, 65-70.
- Schuirmann, D. J. (1987), the two one-sided tests procedure, read off an
  interval.
- Fleiss, J. L., Levin, B., Paik, M. C. (2003). Statistical Methods for
  Rates and Proportions, 3rd ed., eq. 4.14 (sample size, two proportions).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any

__all__ = [
    "DifferenceInterval",
    "EquivalenceResult",
    "FisherResult",
    "HolmResult",
    "InferenceError",
    "OutcomeTally",
    "PowerResult",
    "ProportionInterval",
    "SampleSizeResult",
    "equivalence_by_interval",
    "fisher_exact",
    "holm_bonferroni",
    "n_per_arm_for_power",
    "newcombe_difference",
    "power_two_proportions",
    "tally_outcomes",
    "wilson_interval",
]

_NORMAL = NormalDist()

# R's fisher.test treats tables within this relative error of the observed
# probability as tied; kept so the p-values agree with that reference.
_FISHER_TOLERANCE_NUM = 10**7 + 1
_FISHER_TOLERANCE_DEN = 10**7


class InferenceError(ValueError):
    """Raised when an input is structurally invalid.

    Matches `AgreementError` and `MetricsError`: invalid input is refused
    with a specific reason, never coerced into something that merely looks
    usable.
    """


# --- validation -----------------------------------------------------------


def _count(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InferenceError(f"{name} must be an int, got {type(value).__name__} ({value!r})")
    if value < 0:
        raise InferenceError(f"{name} must be >= 0, got {value}")
    return value


def _open_unit(name: str, value: object) -> float:
    """A float strictly inside (0, 1): alpha, confidence, power, proportions."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InferenceError(f"{name} must be a number, got {type(value).__name__} ({value!r})")
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise InferenceError(f"{name} must be strictly between 0 and 1, got {value!r}")
    return number


def _finite(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InferenceError(f"{name} must be a number, got {type(value).__name__} ({value!r})")
    number = float(value)
    if not math.isfinite(number):
        raise InferenceError(f"{name} must be finite, got {value!r}")
    return number


def _proportion_inputs(prefix: str, successes: object, n: object) -> tuple[int, int]:
    s = _count(f"{prefix}successes", successes)
    total = _count(f"{prefix}n", n)
    if total == 0:
        raise InferenceError(
            f"{prefix}n is 0: a proportion over no usable runs is unknown, not 0 or 1"
        )
    if s > total:
        raise InferenceError(f"{prefix}successes ({s}) exceeds {prefix}n ({total})")
    return s, total


def _z_two_sided(confidence: float) -> float:
    return _NORMAL.inv_cdf(1.0 - (1.0 - confidence) / 2.0)


# --- outcome tally --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeTally:
    """Successes, failures and unknowns, kept apart.

    `n_known` is the denominator every proportion in this module should use.
    `unknown` is reported beside it and never folded into `failures`: a run
    that never reported an outcome is not a failed run.
    """

    successes: int
    failures: int
    unknown: int

    @property
    def n_known(self) -> int:
        return self.successes + self.failures

    @property
    def n_total(self) -> int:
        return self.successes + self.failures + self.unknown

    def to_dict(self) -> dict[str, int]:
        return {
            "failures": self.failures,
            "n_known": self.n_known,
            "successes": self.successes,
            "unknown": self.unknown,
        }


def tally_outcomes(outcomes: Iterable[bool | None]) -> OutcomeTally:
    """Count `True`, `False` and `None`; refuse anything else.

    An int such as `1` is refused rather than read as `True`: a counter that
    leaked into an outcome column should be seen, not absorbed.
    """
    successes = failures = unknown = 0
    for index, outcome in enumerate(outcomes):
        if outcome is None:
            unknown += 1
        elif outcome is True:
            successes += 1
        elif outcome is False:
            failures += 1
        else:
            raise InferenceError(
                f"outcome {index} must be True, False or None, got "
                f"{type(outcome).__name__} ({outcome!r})"
            )
    return OutcomeTally(successes=successes, failures=failures, unknown=unknown)


# --- Wilson interval ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProportionInterval:
    """A proportion and its Wilson score interval.

    Iterating yields `(low, high)`, so `low, high = wilson_interval(...)`
    works.
    """

    successes: int
    n: int
    estimate: float
    low: float
    high: float
    confidence: float
    method: str = "wilson"

    def __iter__(self) -> Iterator[float]:
        yield self.low
        yield self.high

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "estimate": self.estimate,
            "high": self.high,
            "low": self.low,
            "method": self.method,
            "n": self.n,
            "successes": self.successes,
        }


def wilson_interval(successes: int, n: int, *, confidence: float) -> ProportionInterval:
    """Wilson score interval for a binomial proportion.

        centre = (p + z^2/2n) / (1 + z^2/n)
        half   = z / (1 + z^2/n) * sqrt(p(1-p)/n + z^2/4n^2)

    Hand check, 8 of 10 at 95% (z = 1.959964): centre 0.71674, half
    0.22659, so the interval is (0.4902, 0.9433). Unlike the Wald interval
    it stays inside [0, 1] and is not degenerate at 0/n or n/n.

    `n` must be the number of runs with a *known* outcome; n = 0 raises
    because a proportion over nothing is unknown.
    """
    s, total = _proportion_inputs("", successes, n)
    level = _open_unit("confidence", confidence)
    z = _z_two_sided(level)
    p = s / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = (p + z2 / (2.0 * total)) / denom
    half = z / denom * math.sqrt(p * (1.0 - p) / total + z2 / (4.0 * total * total))
    # At the boundary the interval is exact: floating point leaves 1e-17 of
    # slack that would otherwise put the estimate outside its own interval.
    low = 0.0 if s == 0 else max(0.0, centre - half)
    high = 1.0 if s == total else min(1.0, centre + half)
    return ProportionInterval(
        successes=s, n=total, estimate=p, low=low, high=high, confidence=level
    )


# --- Newcombe difference --------------------------------------------------


@dataclass(frozen=True, slots=True)
class DifferenceInterval:
    """Risk difference (treatment - baseline) with a Newcombe interval."""

    successes_treatment: int
    n_treatment: int
    successes_baseline: int
    n_baseline: int
    difference: float
    low: float
    high: float
    confidence: float
    method: str = "newcombe-1998-method-10-hybrid-score"

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence,
            "difference": self.difference,
            "high": self.high,
            "low": self.low,
            "method": self.method,
            "n_baseline": self.n_baseline,
            "n_treatment": self.n_treatment,
            "successes_baseline": self.successes_baseline,
            "successes_treatment": self.successes_treatment,
        }


def newcombe_difference(
    s_treat: int, n_treat: int, s_base: int, n_base: int, *, confidence: float
) -> DifferenceInterval:
    """Newcombe (1998) method 10: hybrid score interval for p1 - p2.

    With (l1, u1) and (l2, u2) the Wilson intervals of the treatment and
    baseline proportions p1 and p2, and d = p1 - p2:

        low  = d - sqrt((p1 - l1)^2 + (u2 - p2)^2)
        high = d + sqrt((u1 - p1)^2 + (p2 - l2)^2)

    Hand check, Newcombe's own example 56/70 against 48/80 at 95%: d = 0.2,
    giving (0.0524, 0.3339). The direction is treatment - baseline, as in
    `metrics.contrasts`.

    For a (1 - 2*alpha) interval to feed `equivalence_by_interval`, pass
    `confidence=1 - 2 * alpha`.
    """
    st, nt = _proportion_inputs("treatment_", s_treat, n_treat)
    sb, nb = _proportion_inputs("baseline_", s_base, n_base)
    treat = wilson_interval(st, nt, confidence=confidence)
    base = wilson_interval(sb, nb, confidence=confidence)
    p1, p2 = treat.estimate, base.estimate
    d = p1 - p2
    low = d - math.sqrt((p1 - treat.low) ** 2 + (base.high - p2) ** 2)
    high = d + math.sqrt((treat.high - p1) ** 2 + (p2 - base.low) ** 2)
    return DifferenceInterval(
        successes_treatment=st,
        n_treatment=nt,
        successes_baseline=sb,
        n_baseline=nb,
        difference=d,
        low=max(-1.0, low),
        high=min(1.0, high),
        confidence=treat.confidence,
    )


# --- Fisher exact ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FisherResult:
    """Two-sided Fisher exact p for [[a, b], [c, d]]."""

    a: int
    b: int
    c: int
    d: int
    p_value: float
    method: str = "fisher-exact-two-sided-sum-of-no-more-probable"

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "c": self.c,
            "d": self.d,
            "method": self.method,
            "p_value": self.p_value,
        }


def fisher_exact(a: int, b: int, c: int, d: int) -> FisherResult:
    """Two-sided exact p for the 2x2 table [[a, b], [c, d]].

    With the margins fixed, the count in cell `a` is hypergeometric:

        P(x) = C(r1, x) * C(r2, c1 - x) / C(n, c1)

    The p-value sums P(x) over every table no more probable than the
    observed one. Probabilities are compared as exact integers (the common
    denominator cancels), with R's relative tolerance of 1e-7 applied in
    integer arithmetic, so there is no float tie-breaking.

    Hand check, [[3, 1], [1, 3]]: P = 1, 16, 36, 16, 1 over 70; the observed
    table has 16, so p = (1 + 16 + 16 + 1) / 70 = 0.4857.
    """
    cells = [_count(name, value) for name, value in zip("abcd", (a, b, c, d), strict=True)]
    a, b, c, d = cells
    n = a + b + c + d
    if n == 0:
        raise InferenceError("fisher_exact needs at least one observation, got an all-zero table")
    r1, r2, c1 = a + b, c + d, a + c

    def weight(x: int) -> int:
        return math.comb(r1, x) * math.comb(r2, c1 - x)

    observed = weight(a)
    total = math.comb(n, c1)
    lo, hi = max(0, c1 - r2), min(r1, c1)
    tied_or_rarer = sum(
        w
        for w in (weight(x) for x in range(lo, hi + 1))
        if w * _FISHER_TOLERANCE_DEN <= observed * _FISHER_TOLERANCE_NUM
    )
    return FisherResult(a=a, b=b, c=c, d=d, p_value=min(1.0, tied_or_rarer / total))


# --- Holm-Bonferroni ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HolmResult:
    """Holm-adjusted p-values and reject flags, in the caller's order."""

    pvalues: tuple[float, ...]
    adjusted: tuple[float, ...]
    reject: tuple[bool, ...]
    alpha: float
    method: str = "holm-bonferroni"

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjusted": list(self.adjusted),
            "alpha": self.alpha,
            "method": self.method,
            "pvalues": list(self.pvalues),
            "reject": list(self.reject),
        }


def holm_bonferroni(pvalues: Sequence[float], *, alpha: float) -> HolmResult:
    """Holm's step-down adjustment, preserving input order.

    Sorted ascending as p(1) <= ... <= p(m), the adjusted values are

        adj(i) = min(1, max over j <= i of (m - j + 1) * p(j))

    which is monotone, and a hypothesis is rejected when adj <= alpha.

    Hand check, p = [0.01, 0.04, 0.03], alpha = 0.05: sorted 0.01, 0.03,
    0.04 give 3 * 0.01 = 0.03, 2 * 0.03 = 0.06, 1 * 0.04 -> 0.06 (monotone),
    so adjusted = [0.03, 0.06, 0.06] and only the first is rejected.
    """
    level = _open_unit("alpha", alpha)
    values = [_p(f"pvalues[{i}]", v) for i, v in enumerate(pvalues)]
    if not values:
        raise InferenceError("holm_bonferroni needs at least one p-value, got none")
    m = len(values)
    order = sorted(range(m), key=lambda i: values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (m - rank) * values[index])
        adjusted[index] = min(1.0, running)
    return HolmResult(
        pvalues=tuple(values),
        adjusted=tuple(adjusted),
        reject=tuple(a <= level for a in adjusted),
        alpha=level,
    )


def _p(name: str, value: object) -> float:
    number = _finite(name, value)
    if not 0.0 <= number <= 1.0:
        raise InferenceError(f"{name} must be in [0, 1], got {value!r}")
    return number


# --- equivalence ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EquivalenceResult:
    """Whether a (1 - 2*alpha) interval lies strictly inside (-margin, +margin)."""

    equivalent: bool
    difference_low: float
    difference_high: float
    margin: float
    alpha: float
    interval_confidence: float
    statement: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "difference_high": self.difference_high,
            "difference_low": self.difference_low,
            "equivalent": self.equivalent,
            "interval_confidence": self.interval_confidence,
            "margin": self.margin,
            "statement": self.statement,
        }


def equivalence_by_interval(
    difference_low: float, difference_high: float, *, margin: float, alpha: float
) -> EquivalenceResult:
    """TOST decision read off a (1 - 2*alpha) confidence interval.

    Two one-sided tests at level alpha reject "the difference is at least
    `margin` in either direction" exactly when the (1 - 2*alpha) interval
    lies strictly inside (-margin, +margin). The caller supplies that
    interval; it must have been built at `confidence = 1 - 2 * alpha`, for
    example:

        alpha = 0.05
        ci = newcombe_difference(s1, n1, s0, n0, confidence=1 - 2 * alpha)
        equivalence_by_interval(ci.low, ci.high, margin=0.10, alpha=alpha)

    **A non-significant difference is not an equivalence result.** An
    interval that straddles zero and is wider than the margin says the data
    cannot rule out a difference of that size; it is silent about
    equivalence. Equivalence is declared only when the whole interval sits
    inside the margin, and `equivalent=False` means "not shown equivalent",
    not "different".

    `margin` and `alpha` are required: the equivalence margin is a
    substantive claim about what difference does not matter, and is still
    undecided in `docs/preregistration-draft.md`. `alpha` must be below 0.5
    so that 1 - 2*alpha is a valid level.
    """
    low = _finite("difference_low", difference_low)
    high = _finite("difference_high", difference_high)
    if low > high:
        raise InferenceError(f"difference_low ({low}) exceeds difference_high ({high})")
    bound = _finite("margin", margin)
    if bound <= 0.0:
        raise InferenceError(f"margin must be > 0, got {margin!r}")
    level = _open_unit("alpha", alpha)
    if level >= 0.5:
        raise InferenceError(
            f"alpha must be below 0.5 so that 1 - 2*alpha is a level, got {alpha!r}"
        )
    equivalent = low > -bound and high < bound
    confidence = 1.0 - 2.0 * level
    if equivalent:
        statement = (
            f"declared equivalent: the {confidence:.0%} interval [{low:+.4f}, {high:+.4f}] "
            f"lies strictly inside +/-{bound:g}"
        )
    else:
        statement = (
            f"not shown equivalent: the {confidence:.0%} interval [{low:+.4f}, {high:+.4f}] "
            f"is not strictly inside +/-{bound:g}; this is not evidence of a difference either"
        )
    return EquivalenceResult(
        equivalent=equivalent,
        difference_low=low,
        difference_high=high,
        margin=bound,
        alpha=level,
        interval_confidence=confidence,
        statement=statement,
    )


# --- power ----------------------------------------------------------------

_POWER_FORMULA = (
    "normal approximation, two-sided two-proportion z-test, pooled-variance null "
    "(Fleiss, Levin & Paik 2003, eq. 4.14), both rejection tails, equal arms"
)


@dataclass(frozen=True, slots=True)
class PowerResult:
    """Power at a stated n, with the assumptions that produced it."""

    power: float
    n_per_arm: int
    p_baseline: float
    p_treatment: float
    alpha: float
    formula: str = _POWER_FORMULA

    def to_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "formula": self.formula,
            "n_per_arm": self.n_per_arm,
            "p_baseline": self.p_baseline,
            "p_treatment": self.p_treatment,
            "power": self.power,
        }


@dataclass(frozen=True, slots=True)
class SampleSizeResult:
    """Smallest n per arm reaching a target power, with its assumptions."""

    n_per_arm: int
    achieved_power: float
    target_power: float
    p_baseline: float
    p_treatment: float
    alpha: float
    formula: str = _POWER_FORMULA

    def to_dict(self) -> dict[str, Any]:
        return {
            "achieved_power": self.achieved_power,
            "alpha": self.alpha,
            "formula": self.formula,
            "n_per_arm": self.n_per_arm,
            "p_baseline": self.p_baseline,
            "p_treatment": self.p_treatment,
            "target_power": self.target_power,
        }


def _power_at(n: int, p0: float, p1: float, alpha: float) -> float:
    z = _z_two_sided(1.0 - alpha)
    pbar = (p0 + p1) / 2.0
    sd_null = math.sqrt(2.0 * pbar * (1.0 - pbar))
    sd_alt = math.sqrt(p0 * (1.0 - p0) + p1 * (1.0 - p1))
    shift = abs(p1 - p0) * math.sqrt(n)
    return _NORMAL.cdf((shift - z * sd_null) / sd_alt) + _NORMAL.cdf(
        (-shift - z * sd_null) / sd_alt
    )


def _proportions(p_baseline: object, p_treatment: object) -> tuple[float, float]:
    # Strictly inside (0, 1): the normal approximation has zero variance at
    # the boundary, and a power figure computed there would be meaningless.
    return _open_unit("p_baseline", p_baseline), _open_unit("p_treatment", p_treatment)


def power_two_proportions(
    p_baseline: float, p_treatment: float, n_per_arm: int, *, alpha: float
) -> PowerResult:
    """Power of a two-sided two-proportion z-test at `n_per_arm` per arm.

        sd0 = sqrt(2 * pbar * (1 - pbar)),  pbar = (p0 + p1) / 2
        sd1 = sqrt(p0 (1 - p0) + p1 (1 - p1))
        power = Phi((|p1 - p0| sqrt(n) - z * sd0) / sd1)
              + Phi((-|p1 - p0| sqrt(n) - z * sd0) / sd1)

    with z the two-sided critical value at `alpha`. When the true effect is
    zero this returns `alpha`, as it should. The assumptions used are
    carried on the result so a report can state them. This is the power of
    a test on independent runs; it does not account for task clustering.
    """
    p0, p1 = _proportions(p_baseline, p_treatment)
    n = _count("n_per_arm", n_per_arm)
    if n < 1:
        raise InferenceError("n_per_arm must be >= 1, got 0")
    level = _open_unit("alpha", alpha)
    return PowerResult(
        power=_power_at(n, p0, p1, level), n_per_arm=n, p_baseline=p0, p_treatment=p1, alpha=level
    )


def n_per_arm_for_power(
    p_baseline: float, p_treatment: float, *, alpha: float, power: float
) -> SampleSizeResult:
    """Smallest n per arm whose power reaches `power`.

    Starts from the closed form (Fleiss, Levin & Paik 2003, eq. 4.14),

        n = (z_a * sd0 + z_b * sd1)^2 / (p1 - p0)^2

    rounded up, then steps down while the one fewer still reaches the
    target under the both-tails power above, so the answer is the minimum
    under exactly the formula `power_two_proportions` uses.

    Raises when the two proportions are equal: no n gives power above alpha
    to detect a difference of zero.
    """
    p0, p1 = _proportions(p_baseline, p_treatment)
    level = _open_unit("alpha", alpha)
    target = _open_unit("power", power)
    if p0 == p1:
        raise InferenceError("p_baseline equals p_treatment: no sample size detects a zero effect")
    z_a = _z_two_sided(1.0 - level)
    z_b = _NORMAL.inv_cdf(target)
    pbar = (p0 + p1) / 2.0
    sd_null = math.sqrt(2.0 * pbar * (1.0 - pbar))
    sd_alt = math.sqrt(p0 * (1.0 - p0) + p1 * (1.0 - p1))
    n = max(1, math.ceil((z_a * sd_null + z_b * sd_alt) ** 2 / (p1 - p0) ** 2))
    while n > 1 and _power_at(n - 1, p0, p1, level) >= target:
        n -= 1
    while _power_at(n, p0, p1, level) < target:
        n += 1
    return SampleSizeResult(
        n_per_arm=n,
        achieved_power=_power_at(n, p0, p1, level),
        target_power=target,
        p_baseline=p0,
        p_treatment=p1,
        alpha=level,
    )
