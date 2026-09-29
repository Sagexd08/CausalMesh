"""Multi-rater kappa coding (`docs/backlog.md`, "Multi-rater kappa coding (§53)").

**What this is, and is not.** §53 asks for *secondary, qualitative* coding of
failure modes — a human reads a run and assigns it a category from a fixed
scheme, independently of what another human assigned, and kappa measures how
much the two agree beyond what chance alone would produce. That is
categorically different from `tasks.outcome.TaskOutcome`: §38's outcome is
"integration tests pass AND induced divergence absent", decided automatically
with zero human judgement, because it is the *only* thing this slice
measures as a primary result. This module must never feed `TaskOutcome`,
`AcceptanceDecision` or any chain event — it has no import of `tasks.outcome`
and nothing in that module imports this one. A judgement recorded here
describes a run; it does not decide one.

**Why this is code-only.** The backlog entry is explicit that "the raters
are the hard part." This module supplies the taxonomy, the input format, and
the kappa arithmetic an operator needs once real raters exist. It ships with
no rater, no transcript coded, and no kappa value computed from real data —
see `docs/backlog.md` and `frontend/content/docs/limitations.mdx` for the
status this leaves the backlog item in.

**The taxonomy.** Every category below names a failure shape this codebase
can actually produce, traced to a concrete source rather than invented from
a generic qualitative-coding rubric:

- `STALE_READ_DIVERGENCE` — `TaskOutcome.divergence_absent` is `False`:
  the induced divergence marker (§38) was still present, meaning an agent
  acted on information that had gone stale rather than noticing the change.
- `CLOBBERED_WRITE` — a later write overwrote an earlier one on a contested
  path without the registry ever refusing it, the failure mode
  `docs/backlog.md`'s "Ownership merge could not express a contested path"
  entry describes directly.
- `DENIED_CLAIM_NOT_SURFACED` — `ClaimRegistry.may_write` or `Gate.check`
  returned a refusal (`ClaimOutcome.granted is False` / `Verdict.refused`)
  but the calling code did not record it (`record_denial` never called, or
  no `POLICY_VERDICT` reached the chain) — the exact shape of
  `docs/backlog.md`'s "Enforcement was unmeasurable, not merely unmeasured."
- `POLICY_REFUSAL_MISHANDLED` — a `Verdict` with `allowed=False` was
  recorded correctly but the agent's own recovery from that refusal made
  the run fail anyway (as opposed to `DENIED_CLAIM_NOT_SURFACED`, where the
  refusal itself went unrecorded).
- `UNRELATED_TEST_FAILURE` — `TaskOutcome.tests_passed` is `False` while
  `divergence_absent` is `True`: the integration suite failed for a reason
  that has nothing to do with coordination (a bug the agent introduced on
  its own, unrelated to any peer's write).
- `RUN_INCOMPLETE` — `TaskOutcome.exit_code is None`
  (`evidence` carries `"integration_test_never_ran"`): the run never reached
  a test result at all — a crash, a hang truncated by the tool-level
  timeout (§22), or a scheduler state that never reached `RUNNING`'s
  terminal edge.
- `ACCEPTANCE_REJECTED_UNCLEAR_CAUSE` — `AcceptanceVerdict.REJECT` was
  reached but the `TaskOutcome.evidence` tuple, read by a human, does not
  point to one of the categories above. This is the deliberate catch-all:
  an unclassifiable rejection is coded as unclear rather than forced into
  a category that does not fit, which is the same "an absent field is
  unknown, never a plausible zero" discipline AGENTS.md states for counters.

A rater assigns exactly one category per run; `note` carries whatever
free-text detail motivated the choice, the same way `Verdict.reason` and
`TaskOutcome.detail` are human-readable sentences rather than codes.

**The math.** Both Cohen's and Fleiss' kappa are implemented directly —
counting and a chance-agreement expectation, a few dozen lines — rather
than importing `statsmodels` or `scikit-learn`. Both already live behind
the `analysis` extra, so the dependency would cost an installer nothing
*additional*, but AGENTS.md's bar is "a reason that survives the question,"
not "already paid for elsewhere," and there is no such reason here: the
formulas are short, exactly specified, and checked below against published
worked examples rather than against themselves.

    Cohen's kappa (two raters), Cohen (1960), Educational and Psychological
    Measurement, 20(1), 37-46:

        kappa = (p_o - p_e) / (1 - p_e)

    where p_o is observed proportion agreement and p_e is the proportion
    expected by chance, computed from each rater's marginal category
    frequencies.

    Fleiss' kappa (N >= 2 raters, N may differ from 2), Fleiss (1971),
    Psychological Bulletin, 76(5), 378-382:

        kappa = (P_bar - P_bar_e) / (1 - P_bar_e)

    where P_bar is the mean per-item observed agreement and P_bar_e is the
    expected agreement from each category's overall proportion across all
    raters and items. Fleiss' formula reduces to Cohen's only when every
    item has exactly 2 raters *and* every rater codes every item with a
    symmetric marginal — the two are close but not identical in general, so
    this module keeps them as two named functions rather than routing the
    N=2 case through Fleiss' formula and calling it Cohen's kappa.

Fleiss' kappa assumes every item was rated by the same number of raters.
An operator's judgement file that violates this is refused with a named
list of the offending items rather than silently dropped from the
computation — the same "a refusal is data" discipline `ClaimOutcome` and
`Verdict` already apply to enforcement.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "AgreementError",
    "FailureModeCategory",
    "KappaResult",
    "RaterJudgement",
    "cohens_kappa",
    "fleiss_kappa",
]


class AgreementError(ValueError):
    """Raised when a judgement or a judgement set is structurally invalid.

    Matches `ClaimError`/`EdgeValidationError`'s convention: invalid input
    is refused at construction with a specific reason, never coerced into
    something that merely looks usable.
    """


class FailureModeCategory(StrEnum):
    """The fixed taxonomy §53 codes runs against.

    A `StrEnum` so the canonical on-disk form is the member's own string
    value, the convention `events.schema.EventType` and `edges.types.
    RelationshipType` already set. Every member is grounded in a concrete
    failure shape this codebase can produce — see the module docstring for
    the source of each. The set is closed on purpose: an operator's
    judgement file naming a category outside it is a structural error
    (`RaterJudgement.__post_init__`), not a value silently accepted and
    then never seen in any report.
    """

    STALE_READ_DIVERGENCE = "STALE_READ_DIVERGENCE"
    CLOBBERED_WRITE = "CLOBBERED_WRITE"
    DENIED_CLAIM_NOT_SURFACED = "DENIED_CLAIM_NOT_SURFACED"
    POLICY_REFUSAL_MISHANDLED = "POLICY_REFUSAL_MISHANDLED"
    UNRELATED_TEST_FAILURE = "UNRELATED_TEST_FAILURE"
    RUN_INCOMPLETE = "RUN_INCOMPLETE"
    ACCEPTANCE_REJECTED_UNCLEAR_CAUSE = "ACCEPTANCE_REJECTED_UNCLEAR_CAUSE"


@dataclass(frozen=True, slots=True)
class RaterJudgement:
    """One rater's coding of one run against the fixed taxonomy.

    `item_id` identifies what was coded (a `run_id`, matching the id every
    run artifact already carries) rather than embedding the run's content —
    a judgement is a pointer to evidence a human read, the same separation
    `CausalEdge` keeps between an edge and the events it names.

    Validated eagerly, in `__post_init__`, so a judgement that fails
    validation never enters a kappa computation silently truncated or
    coerced — matching `AGENTS.md`'s "a refusal is data": an unknown
    category is rejected outright, never mapped to the nearest known one.
    """

    item_id: str
    rater_id: str
    category: FailureModeCategory
    note: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise AgreementError(f"item_id must be a non-empty string, got {self.item_id!r}")
        if not isinstance(self.rater_id, str) or not self.rater_id.strip():
            raise AgreementError(f"rater_id must be a non-empty string, got {self.rater_id!r}")
        if not isinstance(self.category, FailureModeCategory):
            raise AgreementError(
                f"category must be a FailureModeCategory, got {type(self.category).__name__} "
                f"({self.category!r}); known categories are "
                f"{[str(c) for c in FailureModeCategory]}"
            )
        if not isinstance(self.note, str):
            raise AgreementError(f"note must be a string, got {type(self.note).__name__}")

    def to_dict(self) -> dict[str, str]:
        return {
            "item_id": self.item_id,
            "rater_id": self.rater_id,
            "category": str(self.category),
            "note": self.note,
        }

    @staticmethod
    def from_dict(record: dict[str, Any]) -> RaterJudgement:
        """Rebuild a `RaterJudgement` from a parsed JSON/YAML record.

        Raises `AgreementError` on anything structurally unusable, including
        a category string outside `FailureModeCategory` — never coerced,
        never silently dropped. Matches `CausalEdge.from_dict`'s discipline
        of reconstructing through the validating constructor rather than
        trusting a stored record.
        """
        try:
            item_id = record["item_id"]
            rater_id = record["rater_id"]
            category_raw = record["category"]
        except KeyError as exc:
            raise AgreementError(f"judgement record is missing field {exc}") from exc

        if not isinstance(category_raw, str):
            raise AgreementError(f"category must be a string, got {type(category_raw).__name__}")
        try:
            category = FailureModeCategory(category_raw)
        except ValueError as exc:
            raise AgreementError(
                f"category {category_raw!r} is not one of {[str(c) for c in FailureModeCategory]}"
            ) from exc

        note = record.get("note", "")
        if not isinstance(note, str):
            raise AgreementError(f"note must be a string, got {type(note).__name__}")
        if not isinstance(item_id, str) or not isinstance(rater_id, str):
            raise AgreementError("item_id and rater_id must be strings")

        return RaterJudgement(item_id=item_id, rater_id=rater_id, category=category, note=note)


@dataclass(frozen=True, slots=True)
class KappaResult:
    """A kappa value, with the observed/expected figures it was computed from.

    Matching `TaskOutcome.evidence` and `AcceptanceDecision.evidence`: a
    kappa number is never reported detached from what produced it.
    `observed_agreement` and `expected_agreement` are the p_o/p_e (Cohen)
    or P_bar/P_bar_e (Fleiss) terms named in the module docstring, kept as
    plain `float` — descriptive statistics, not ledger money, so `Decimal`
    does not apply here (AGENTS.md's Decimal rule is scoped to money).
    """

    kappa: float
    observed_agreement: float
    expected_agreement: float
    method: str
    n_items: int
    n_raters: int
    categories: tuple[FailureModeCategory, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "categories": [str(c) for c in self.categories],
            "expected_agreement": self.expected_agreement,
            "kappa": self.kappa,
            "method": self.method,
            "n_items": self.n_items,
            "n_raters": self.n_raters,
            "observed_agreement": self.observed_agreement,
        }


def _group_by_item(judgements: tuple[RaterJudgement, ...]) -> dict[str, list[RaterJudgement]]:
    grouped: dict[str, list[RaterJudgement]] = {}
    for judgement in judgements:
        grouped.setdefault(judgement.item_id, []).append(judgement)
    return grouped


def cohens_kappa(judgements: tuple[RaterJudgement, ...]) -> KappaResult:
    """Cohen's kappa for exactly two raters coding the same set of items.

    Cohen, J. (1960). "A coefficient of agreement for nominal scales."
    Educational and Psychological Measurement, 20(1), 37-46.

        p_o = (number of items both raters agree on) / (number of items)
        p_e = sum over categories c of P(rater_1 = c) * P(rater_2 = c)
        kappa = (p_o - p_e) / (1 - p_e)

    Refuses (rather than silently ignoring) anything other than exactly two
    distinct raters, or an item not coded by both of them — a two-rater
    formula given three raters' data would either be wrong or would have
    to guess which two to use, and guessing is exactly what this module's
    validation discipline exists to avoid.
    """
    if not judgements:
        raise AgreementError("cohens_kappa needs at least one judgement, got none")

    rater_ids = sorted({j.rater_id for j in judgements})
    if len(rater_ids) != 2:
        raise AgreementError(
            f"cohens_kappa needs exactly 2 raters, got {len(rater_ids)}: {rater_ids}. "
            "Use fleiss_kappa for 3 or more raters."
        )
    rater_a, rater_b = rater_ids

    by_item = _group_by_item(judgements)
    incomplete = [
        item_id
        for item_id, item_judgements in by_item.items()
        if {j.rater_id for j in item_judgements} != {rater_a, rater_b}
    ]
    if incomplete:
        raise AgreementError(
            "cohens_kappa needs both raters to have coded every item; "
            f"not rated by both {rater_a!r} and {rater_b!r}: {sorted(incomplete)}"
        )
    duplicated = [
        item_id for item_id, item_judgements in by_item.items() if len(item_judgements) != 2
    ]
    if duplicated:
        raise AgreementError(
            f"cohens_kappa needs exactly one judgement per rater per item; "
            f"items with a duplicate or missing judgement: {sorted(duplicated)}"
        )

    items = sorted(by_item)
    pairs = []
    for item_id in items:
        by_rater = {j.rater_id: j.category for j in by_item[item_id]}
        pairs.append((by_rater[rater_a], by_rater[rater_b]))

    n = len(pairs)
    agree = sum(1 for a, b in pairs if a == b)
    p_o = agree / n

    counts_a = Counter(a for a, _ in pairs)
    counts_b = Counter(b for _, b in pairs)
    categories = tuple(sorted({*counts_a, *counts_b}, key=str))
    p_e = sum((counts_a[c] / n) * (counts_b[c] / n) for c in categories)

    kappa = 1.0 if p_e == 1.0 else (p_o - p_e) / (1 - p_e)

    return KappaResult(
        kappa=kappa,
        observed_agreement=p_o,
        expected_agreement=p_e,
        method="cohen",
        n_items=n,
        n_raters=2,
        categories=categories,
    )


def fleiss_kappa(judgements: tuple[RaterJudgement, ...]) -> KappaResult:
    """Fleiss' kappa for N >= 2 raters coding the same set of items.

    Fleiss, J. L. (1971). "Measuring nominal scale agreement among many
    raters." Psychological Bulletin, 76(5), 378-382.

    Standard Fleiss' kappa assumes every item received the same number of
    ratings. This is validated up front and refused with the offending
    item ids named, rather than dropping mismatched items and computing
    over whatever remains — a silently reduced item set would answer a
    different, unstated question and report it under the same name.

        For item i, category c: n_ic = number of raters assigning c to i.
        P_i = (sum_c n_ic * (n_ic - 1)) / (n * (n - 1))   -- item i's agreement
        P_bar = mean over items of P_i
        p_c = (sum_i n_ic) / (N * n)                       -- category c's overall share
        P_bar_e = sum_c p_c^2
        kappa = (P_bar - P_bar_e) / (1 - P_bar_e)

    where n is raters per item (constant) and N is the number of items.
    With exactly 2 raters per item this is closely related to, but not
    algebraically identical to, `cohens_kappa` in general (see the module
    docstring) — both are provided rather than one routed through the
    other.
    """
    if not judgements:
        raise AgreementError("fleiss_kappa needs at least one judgement, got none")

    rater_ids = {j.rater_id for j in judgements}
    if len(rater_ids) < 2:
        raise AgreementError(
            f"fleiss_kappa needs at least 2 distinct raters, got {len(rater_ids)}: "
            f"{sorted(rater_ids)}"
        )

    by_item = _group_by_item(judgements)
    for item_id, item_judgements in by_item.items():
        seen_raters = [j.rater_id for j in item_judgements]
        if len(seen_raters) != len(set(seen_raters)):
            raise AgreementError(
                f"fleiss_kappa needs at most one judgement per rater per item; "
                f"item {item_id!r} has a duplicate rater in {sorted(seen_raters)}"
            )

    raters_per_item = {item_id: len(js) for item_id, js in by_item.items()}
    distinct_counts = set(raters_per_item.values())
    if len(distinct_counts) != 1:
        raise AgreementError(
            "fleiss_kappa requires every item to be rated by the same number of raters "
            f"(the standard Fleiss precondition); got counts {sorted(distinct_counts)} across "
            f"items: {raters_per_item}"
        )
    n = distinct_counts.pop()
    if n < 2:
        raise AgreementError(f"fleiss_kappa needs at least 2 raters per item, got {n}")

    items = sorted(by_item)
    all_categories = tuple(sorted({j.category for j in judgements}, key=str))

    n_ic: dict[str, Counter[FailureModeCategory]] = {
        item_id: Counter(j.category for j in by_item[item_id]) for item_id in items
    }

    num_items = len(items)
    item_agreements = []
    for item_id in items:
        counts = n_ic[item_id]
        pairwise_agree = sum(count * (count - 1) for count in counts.values())
        item_agreements.append(pairwise_agree / (n * (n - 1)))
    p_bar = sum(item_agreements) / num_items

    category_totals = Counter()
    for item_id in items:
        category_totals.update(n_ic[item_id])
    total_ratings = num_items * n
    category_shares = {c: category_totals[c] / total_ratings for c in all_categories}
    p_bar_e = sum(share**2 for share in category_shares.values())

    kappa = 1.0 if p_bar_e == 1.0 else (p_bar - p_bar_e) / (1 - p_bar_e)

    return KappaResult(
        kappa=kappa,
        observed_agreement=p_bar,
        expected_agreement=p_bar_e,
        method="fleiss",
        n_items=num_items,
        n_raters=n,
        categories=all_categories,
    )
