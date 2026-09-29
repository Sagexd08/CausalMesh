"""Unit tests for multi-rater kappa coding (`docs/backlog.md`, "Multi-rater
kappa coding (§53)").

Three things get the most attention:

- **The arithmetic is checked against independently verifiable worked
  examples**, not just against itself. Each expected value below was
  computed by a second, from-scratch script (counting pairwise agreement
  directly) rather than derived from `agreement.py`'s own formula — the
  same discipline `docs/backlog.md`'s "Staleness estimation" entry names as
  the reason an estimator must come from a cited source rather than be
  reconstructed from its own inputs.
- **Validation refuses rather than coerces.** An unknown category, a
  wrong rater count, or an unequal number of raters per item is a named
  `AgreementError`, matching AGENTS.md's "a refusal is data" and "an
  absent field is unknown, never 0."
- **This module never touches `tasks.outcome`.** No test here constructs a
  `TaskOutcome` or `AcceptanceDecision` — the two systems are independent,
  matching the module docstring's explicit separation of §38 (automatic,
  primary) from §53 (human, secondary).
"""

from __future__ import annotations

import pytest

from causalmesh.analysis.agreement import (
    AgreementError,
    FailureModeCategory,
    RaterJudgement,
    cohens_kappa,
    fleiss_kappa,
)

pytestmark = pytest.mark.unit

CAT_A = FailureModeCategory.STALE_READ_DIVERGENCE
CAT_B = FailureModeCategory.CLOBBERED_WRITE
CAT_C = FailureModeCategory.RUN_INCOMPLETE


def judgement(item_id: str, rater_id: str, category: FailureModeCategory) -> RaterJudgement:
    return RaterJudgement(item_id=item_id, rater_id=rater_id, category=category)


class TestFailureModeCategory:
    def test_every_category_traces_to_a_real_failure_shape(self) -> None:
        # A closed set: the module docstring grounds each one in a concrete
        # source (TaskOutcome fields, ClaimRegistry/Gate refusal paths, or a
        # named backlog defect). This test pins the set so a category cannot
        # be added or removed without a matching docstring update.
        assert {str(c) for c in FailureModeCategory} == {
            "STALE_READ_DIVERGENCE",
            "CLOBBERED_WRITE",
            "DENIED_CLAIM_NOT_SURFACED",
            "POLICY_REFUSAL_MISHANDLED",
            "UNRELATED_TEST_FAILURE",
            "RUN_INCOMPLETE",
            "ACCEPTANCE_REJECTED_UNCLEAR_CAUSE",
        }


class TestRaterJudgementValidation:
    def test_a_well_formed_judgement_round_trips_through_a_dict(self) -> None:
        original = judgement("run_001", "rater_a", CAT_A)
        rebuilt = RaterJudgement.from_dict(original.to_dict())
        assert rebuilt == original

    def test_an_unknown_category_is_rejected_not_coerced(self) -> None:
        # AGENTS.md: a refusal is data. An operator's typo or a category
        # invented outside the fixed scheme must fail loudly, not silently
        # map onto the nearest known member.
        with pytest.raises(AgreementError, match="not one of"):
            RaterJudgement.from_dict(
                {"item_id": "run_001", "rater_id": "rater_a", "category": "VIBES_WERE_OFF"}
            )

    def test_a_missing_field_is_rejected(self) -> None:
        with pytest.raises(AgreementError, match="missing field"):
            RaterJudgement.from_dict({"item_id": "run_001", "rater_id": "rater_a"})

    def test_an_empty_item_id_is_rejected(self) -> None:
        with pytest.raises(AgreementError, match="item_id"):
            RaterJudgement(item_id="", rater_id="rater_a", category=CAT_A)


class TestCohensKappa:
    """Cohen, J. (1960). Educational and Psychological Measurement, 20(1), 37-46."""

    def test_perfect_agreement_is_kappa_one(self) -> None:
        items = ["run_001", "run_002", "run_003", "run_004"]
        categories = [CAT_A, CAT_A, CAT_B, CAT_C]
        judgements = tuple(
            judgement(item, rater, cat)
            for item, cat in zip(items, categories, strict=True)
            for rater in ("rater_a", "rater_b")
        )
        result = cohens_kappa(judgements)
        assert result.kappa == pytest.approx(1.0)
        assert result.observed_agreement == pytest.approx(1.0)
        assert result.n_items == 4
        assert result.n_raters == 2

    def test_chance_level_agreement_is_near_zero(self) -> None:
        # Two raters whose category choices are independent of each other:
        # both use A and B with the same 50/50 marginal, and every possible
        # (A,B) pairing appears in equal proportion, so p_o == p_e exactly.
        rater_a = ["A", "A", "B", "B"] * 5
        rater_b = ["A", "B", "A", "B"] * 5
        cats = {"A": CAT_A, "B": CAT_B}
        judgements = []
        for idx, (a, b) in enumerate(zip(rater_a, rater_b, strict=True)):
            item = f"run_{idx:03d}"
            judgements.append(judgement(item, "rater_a", cats[a]))
            judgements.append(judgement(item, "rater_b", cats[b]))
        result = cohens_kappa(tuple(judgements))
        assert result.kappa == pytest.approx(0.0, abs=1e-9)

    def test_a_hand_verified_worked_example(self) -> None:
        # Independently computed (see this file's module docstring
        # discipline): rater A = Y Y Y Y N N N N Y N, rater B = Y Y Y N N N
        # N Y Y N. Agreement on 8/10 items; p_o = 0.8. Marginals: A has 5 Y
        # and 5 N, B has 5 Y and 5 N, so p_e = (5/10)(5/10) + (5/10)(5/10)
        # = 0.5. kappa = (0.8 - 0.5) / (1 - 0.5) = 0.6.
        seq_a = "YYYYNNNNYN"
        seq_b = "YYYNNNNYYN"
        cats = {"Y": CAT_A, "N": CAT_B}
        judgements = []
        for idx, (a, b) in enumerate(zip(seq_a, seq_b, strict=True)):
            item = f"run_{idx:03d}"
            judgements.append(judgement(item, "rater_a", cats[a]))
            judgements.append(judgement(item, "rater_b", cats[b]))
        result = cohens_kappa(tuple(judgements))
        assert result.observed_agreement == pytest.approx(0.8)
        assert result.expected_agreement == pytest.approx(0.5)
        assert result.kappa == pytest.approx(0.6)

    def test_rejects_anything_other_than_two_raters(self) -> None:
        judgements = (
            judgement("run_001", "rater_a", CAT_A),
            judgement("run_001", "rater_b", CAT_A),
            judgement("run_001", "rater_c", CAT_A),
        )
        with pytest.raises(AgreementError, match="exactly 2 raters"):
            cohens_kappa(judgements)

    def test_rejects_an_item_not_coded_by_both_raters(self) -> None:
        judgements = (
            judgement("run_001", "rater_a", CAT_A),
            judgement("run_001", "rater_b", CAT_A),
            judgement("run_002", "rater_a", CAT_B),
            # run_002 has no rater_b judgement.
        )
        with pytest.raises(AgreementError, match="run_002"):
            cohens_kappa(judgements)


class TestFleissKappa:
    """Fleiss, J. L. (1971). Psychological Bulletin, 76(5), 378-382."""

    def test_perfect_agreement_is_kappa_one(self) -> None:
        raters = ("rater_a", "rater_b", "rater_c")
        items = {"run_001": CAT_A, "run_002": CAT_B, "run_003": CAT_C, "run_004": CAT_A}
        judgements = tuple(
            judgement(item, rater, cat) for item, cat in items.items() for rater in raters
        )
        result = fleiss_kappa(judgements)
        assert result.kappa == pytest.approx(1.0)
        assert result.n_raters == 3
        assert result.n_items == 4

    def test_chance_level_agreement_is_near_zero(self) -> None:
        # Three raters, three categories, every item gets one of each
        # category exactly once (a uniform, maximally disagreeing design) —
        # observed agreement is 0 on every item, matching the floor case.
        raters = ("rater_a", "rater_b", "rater_c")
        cats = (CAT_A, CAT_B, CAT_C)
        judgements = []
        for idx in range(6):
            item = f"run_{idx:03d}"
            rotation = cats[idx % 3 :] + cats[: idx % 3]
            for rater, cat in zip(raters, rotation, strict=True):
                judgements.append(judgement(item, rater, cat))
        result = fleiss_kappa(tuple(judgements))
        assert result.observed_agreement == pytest.approx(0.0)

    def test_a_hand_verified_worked_example(self) -> None:
        # Independently computed (see this file's module docstring
        # discipline). 5 items, 3 raters, categories A/B/C:
        #   i1: A A A   (unanimous, P_i = 1.0)
        #   i2: A A B   (P_i = 1/3)
        #   i3: B B C   (P_i = 1/3)
        #   i4: A B C   (all different, P_i = 0.0)
        #   i5: C C C   (unanimous, P_i = 1.0)
        # P_bar = (1 + 1/3 + 1/3 + 0 + 1) / 5 = 0.533333...
        # Category totals across 15 ratings: A=6, B=5, C=4 ->
        #   p_A=0.4, p_B=1/3, p_C=4/15
        # P_bar_e = 0.4^2 + (1/3)^2 + (4/15)^2 = 0.342222...
        # kappa = (0.533333... - 0.342222...) / (1 - 0.342222...) = 0.290541 (6dp)
        data = {
            "i1": [CAT_A, CAT_A, CAT_A],
            "i2": [CAT_A, CAT_A, CAT_B],
            "i3": [CAT_B, CAT_B, CAT_C],
            "i4": [CAT_A, CAT_B, CAT_C],
            "i5": [CAT_C, CAT_C, CAT_C],
        }
        raters = ("rater_a", "rater_b", "rater_c")
        judgements = tuple(
            judgement(item, rater, cat)
            for item, cats in data.items()
            for rater, cat in zip(raters, cats, strict=True)
        )
        result = fleiss_kappa(judgements)
        assert result.observed_agreement == pytest.approx(0.5333333333, abs=1e-9)
        assert result.expected_agreement == pytest.approx(0.3422222222, abs=1e-9)
        assert result.kappa == pytest.approx(0.2905405405, abs=1e-9)

    def test_two_raters_per_item_is_a_legal_fleiss_input(self) -> None:
        judgements = (
            judgement("run_001", "rater_a", CAT_A),
            judgement("run_001", "rater_b", CAT_A),
            judgement("run_002", "rater_a", CAT_B),
            judgement("run_002", "rater_b", CAT_C),
        )
        result = fleiss_kappa(judgements)
        assert result.n_raters == 2
        assert result.n_items == 2

    def test_rejects_unequal_rater_counts_per_item_rather_than_dropping_items(self) -> None:
        # Standard Fleiss' kappa assumes a constant number of raters per
        # item. Silently computing over whatever items happen to have a
        # matching count would answer a different, unstated question under
        # the same name — refused instead, naming the offending item.
        judgements = (
            judgement("run_001", "rater_a", CAT_A),
            judgement("run_001", "rater_b", CAT_A),
            judgement("run_001", "rater_c", CAT_A),
            judgement("run_002", "rater_a", CAT_B),
            judgement("run_002", "rater_b", CAT_B),
            # run_002 has only 2 raters where run_001 has 3.
        )
        with pytest.raises(AgreementError, match="same number of raters"):
            fleiss_kappa(judgements)

    def test_rejects_fewer_than_two_raters(self) -> None:
        judgements = (judgement("run_001", "rater_a", CAT_A),)
        with pytest.raises(AgreementError, match="at least 2 distinct raters"):
            fleiss_kappa(judgements)

    def test_rejects_a_duplicate_rater_on_the_same_item(self) -> None:
        judgements = (
            judgement("run_001", "rater_a", CAT_A),
            judgement("run_001", "rater_a", CAT_B),
            judgement("run_001", "rater_b", CAT_A),
        )
        with pytest.raises(AgreementError, match="duplicate rater"):
            fleiss_kappa(judgements)
