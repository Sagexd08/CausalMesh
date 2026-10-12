"""A report over one collection: counts, intervals and the primary contrasts.

**What this is, and is not.** A tabulation of what one collection recorded,
with the interval and test primitives of `causalmesh.analysis.inference`
applied under assumptions the *caller* states. It is `docs/PLAN.md` Step 14's
report generator, and nothing more:

- It emits only `PILOT` (what the runs recorded) and `DERIVED` (computed from
  those counts). `CONFIRMATORY` is gated until a preregistration is signed
  (`docs/backlog.md`), so this builder asserts it never emits it.
- `alpha`, `confidence` and `margin` are required arguments with no default,
  and the report says so on its face: they are not preregistered
  (`docs/preregistration-draft.md` is an unsigned draft).
- Runs are treated as independent trials. The planned mixed-effects model
  with task random intercepts is not built, so pooling across tasks, or
  across runs that share a task, is a simplification the report states.
- An outcome that was never recorded is `unknown`: excluded from every
  denominator and reported beside it, never counted as a failure. A contrast
  with no usable run in either arm is `unknown`, never 0.

**Provenance.** Every number carries the run ids it was computed from, under
`sources` in the row, so a figure can be traced back to run artifacts.
`to_dict()` is reproducible: no wall-clock, hostname or absolute path.
"""

from __future__ import annotations

import hashlib
import textwrap
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from causalmesh.analysis.inference import (
    DifferenceInterval,
    EquivalenceResult,
    FisherResult,
    InferenceError,
    OutcomeTally,
    equivalence_by_interval,
    fisher_exact,
    holm_bonferroni,
    newcombe_difference,
    tally_outcomes,
    wilson_interval,
)
from causalmesh.experiments.arms import ARM_IDS, PRIMARY_CONTRASTS, Contrast, arm as _known_arm
from causalmesh.metrics.accounting import ArmMetrics, CollectionMetrics

__all__ = [
    "EMITTABLE_LABELS",
    "LABELS",
    "ArmRow",
    "ContrastRow",
    "Report",
    "ReportError",
    "build_report",
    "render_text",
]

# The five labels section 68 names. This builder emits two of them.
LABELS: tuple[str, ...] = ("ANALYTICAL", "PILOT", "CONFIRMATORY", "EXPLORATORY", "DERIVED")
EMITTABLE_LABELS: tuple[str, ...] = ("PILOT", "DERIVED")

_NOT_PREREGISTERED = (
    "alpha, confidence and margin were supplied by the caller and are NOT preregistered: "
    "docs/preregistration-draft.md is an unsigned draft"
)

_WIDTH = 100

# Table-width spellings of the verdicts; `to_dict()` carries the full ones.
_SHORT_VERDICT = {
    "equivalent": "EQUIV",
    "not shown equivalent": "not shown",
    "not assessed": "n/a",
    "unknown": "unknown",
}


class ReportError(ValueError):
    """Raised when a report cannot be built honestly from what it was given."""


@dataclass(frozen=True, slots=True)
class ArmRow:
    """One arm's counts. `n` counts runs with a known outcome only."""

    arm: str
    runs: int
    n: int
    successes: int
    failures: int
    unknown: int
    success_rate: float | None
    ci_low: float | None
    ci_high: float | None
    diff_vs_baseline: float | None
    diff_low: float | None
    diff_high: float | None
    sources: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "ci_high": self.ci_high,
            "ci_low": self.ci_low,
            "diff_high": self.diff_high,
            "diff_low": self.diff_low,
            "diff_vs_baseline": self.diff_vs_baseline,
            "failures": self.failures,
            "n": self.n,
            "runs": self.runs,
            "sources": {k: list(v) for k, v in sorted(self.sources.items())},
            "success_rate": self.success_rate,
            "successes": self.successes,
            "unknown": self.unknown,
        }


@dataclass(frozen=True, slots=True)
class ContrastRow:
    """One planned contrast, treatment - baseline.

    `status` is `measured` or `unknown`. When unknown every statistic is
    None and `reason` says why; the counts are still the real counts.
    """

    name: str
    baseline: str
    treatment: str
    isolates: str
    status: str
    reason: str | None
    n_baseline: int
    n_treatment: int
    successes_baseline: int | None
    successes_treatment: int | None
    difference: float | None
    ci_low: float | None
    ci_high: float | None
    fisher_p: float | None
    holm_adjusted_p: float | None
    holm_reject: bool | None
    equivalence: str
    equivalence_detail: Mapping[str, Any] | None
    sources: Mapping[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline": self.baseline,
            "ci_high": self.ci_high,
            "ci_low": self.ci_low,
            "difference": self.difference,
            "equivalence": self.equivalence,
            "equivalence_detail": None
            if self.equivalence_detail is None
            else dict(sorted(self.equivalence_detail.items())),
            "fisher_p": self.fisher_p,
            "holm_adjusted_p": self.holm_adjusted_p,
            "holm_reject": self.holm_reject,
            "isolates": self.isolates,
            "n_baseline": self.n_baseline,
            "n_treatment": self.n_treatment,
            "name": self.name,
            "reason": self.reason,
            "sources": {k: list(v) for k, v in sorted(self.sources.items())},
            "status": self.status,
            "successes_baseline": self.successes_baseline,
            "successes_treatment": self.successes_treatment,
            "treatment": self.treatment,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """A built report. Two tables, each with a label, and the assumptions."""

    experiment_id: str
    task_id: str | None
    alpha: float
    confidence: float
    margin: float | None
    baseline_arm: str
    arm_label: str
    arms: tuple[ArmRow, ...]
    contrast_label: str
    contrasts: tuple[ContrastRow, ...]
    holm_family: tuple[str, ...]
    notes: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        for label in (self.arm_label, self.contrast_label):
            if label not in LABELS:
                raise ReportError(f"unknown table label {label!r}; the labels are {list(LABELS)}")
            if label not in EMITTABLE_LABELS:
                raise ReportError(
                    f"this builder may not emit {label!r}: CONFIRMATORY is gated until a "
                    "preregistration is signed, and the other labels are not applied here"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assumptions": {
                "alpha": self.alpha,
                "baseline_arm": self.baseline_arm,
                "confidence": self.confidence,
                "margin": self.margin,
                "preregistered": False,
                "statement": _NOT_PREREGISTERED,
            },
            "experiment_id": self.experiment_id,
            "notes": list(self.notes),
            "tables": {
                "arms": {
                    "label": self.arm_label,
                    "rows": [row.to_dict() for row in self.arms],
                },
                "contrasts": {
                    "holm_family": list(self.holm_family),
                    "label": self.contrast_label,
                    "rows": [row.to_dict() for row in self.contrasts],
                },
            },
            "task_id": self.task_id,
        }


# --- building -------------------------------------------------------------


def _ids(arm: ArmMetrics | None, *, known: bool) -> tuple[str, ...]:
    runs = arm.runs if arm is not None else []
    return tuple(sorted(r.run_id for r in runs if r.outcome_known == known))


def _tally(arm: ArmMetrics | None) -> OutcomeTally:
    return tally_outcomes(r.succeeded for r in (arm.runs if arm is not None else []))


def _union(*groups: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({run_id for group in groups for run_id in group}))


def _arm_order(arm_id: str) -> tuple[int, str]:
    return (ARM_IDS.index(arm_id), arm_id) if arm_id in ARM_IDS else (len(ARM_IDS), arm_id)


def _arm_row(
    arm_id: str,
    arm: ArmMetrics,
    baseline: ArmMetrics | None,
    *,
    baseline_arm: str,
    confidence: float,
) -> ArmRow:
    tally = _tally(arm)
    known, unknown = _ids(arm, known=True), _ids(arm, known=False)
    rate = low = high = diff = diff_low = diff_high = None
    if tally.n_known >= 1:
        interval = wilson_interval(tally.successes, tally.n_known, confidence=confidence)
        rate, low, high = interval.estimate, interval.low, interval.high
        base = _tally(baseline)
        if arm_id != baseline_arm and base.n_known >= 1:
            delta = newcombe_difference(
                tally.successes,
                tally.n_known,
                base.successes,
                base.n_known,
                confidence=confidence,
            )
            diff, diff_low, diff_high = delta.difference, delta.low, delta.high
    against = _union(known, _ids(baseline, known=True))
    sources = {
        "n": known,
        "successes": known,
        "failures": known,
        "success_rate": known,
        "ci_low": known,
        "ci_high": known,
        "unknown": unknown,
        "diff_vs_baseline": against,
        "diff_low": against,
        "diff_high": against,
    }
    return ArmRow(
        arm=arm_id,
        runs=arm.run_count,
        n=tally.n_known,
        successes=tally.successes,
        failures=tally.failures,
        unknown=tally.unknown,
        success_rate=rate,
        ci_low=low,
        ci_high=high,
        diff_vs_baseline=diff,
        diff_low=diff_low,
        diff_high=diff_high,
        sources=sources,
    )


@dataclass(frozen=True, slots=True)
class _Staged:
    """One contrast after pass one, before the Holm family is known."""

    contrast: Contrast
    bt: OutcomeTally
    tt: OutcomeTally
    known: tuple[str, ...]
    reason: str | None
    diff: DifferenceInterval | None
    fisher: FisherResult | None
    equiv: EquivalenceResult | None


def build_report(
    collection: CollectionMetrics,
    *,
    confidence: float,
    alpha: float,
    margin: float | None = None,
    baseline_arm: str = "C0",
    task_id: str | None = None,
) -> Report:
    """Build a PILOT/DERIVED report over `collection`.

    `confidence` sets the Wilson and Newcombe intervals; `alpha` sets the
    Holm family-wise level; `margin`, when given, adds a TOST-style
    equivalence verdict on a (1 - 2*alpha) interval, in proportion units
    (0.10 is ten percentage points). None of the three has a default that
    this function would choose for the caller, except that `margin=None`
    means "no equivalence assessment".

    `task_id` restricts to one task. Pooling across tasks is the default
    only because it is the whole collection; on this design it can be
    misleading (see `causalmesh.metrics.accounting.CollectionMetrics.by_task`)
    and the report says so when it happens.
    """
    # Validated by the primitives below, but up front so the message names
    # the argument the caller passed rather than a derived level.
    for name, value in (("confidence", confidence), ("alpha", alpha)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
            raise InferenceError(f"{name} must be strictly between 0 and 1, got {value!r}")
    if margin is not None:
        if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not margin > 0:
            raise InferenceError(f"margin must be a number > 0, got {margin!r}")
        if not alpha < 0.5:
            raise InferenceError(
                f"alpha must be below 0.5 to assess equivalence (1 - 2*alpha is the interval "
                f"level), got {alpha!r}"
            )
    try:
        _known_arm(baseline_arm)
    except ValueError as exc:
        raise ReportError(str(exc)) from exc
    if task_id is not None and task_id not in collection.task_ids:
        raise ReportError(f"unknown task {task_id!r}; this collection ran {collection.task_ids}")

    arms = collection.by_task(task_id) if task_id is not None else collection.arms
    baseline = arms.get(baseline_arm)

    arm_rows = tuple(
        _arm_row(arm_id, arms[arm_id], baseline, baseline_arm=baseline_arm, confidence=confidence)
        for arm_id in sorted(arms, key=_arm_order)
    )

    # Pass one: everything that does not depend on the other contrasts.
    staged: list[_Staged] = []
    for contrast in PRIMARY_CONTRASTS:
        base, treat = arms.get(contrast.baseline), arms.get(contrast.treatment)
        bt, tt = _tally(base), _tally(treat)
        known = _union(_ids(base, known=True), _ids(treat, known=True))
        reason = None
        if bt.n_known < 1 or tt.n_known < 1:
            empty = [
                f"{arm_id} has {'no runs' if arms.get(arm_id) is None else 'no usable outcome'}"
                for arm_id, t in ((contrast.baseline, bt), (contrast.treatment, tt))
                if t.n_known < 1
            ]
            reason = "; ".join(empty)
            staged.append(_Staged(contrast, bt, tt, known, reason, None, None, None))
            continue
        diff = newcombe_difference(
            tt.successes, tt.n_known, bt.successes, bt.n_known, confidence=confidence
        )
        fisher = fisher_exact(tt.successes, tt.failures, bt.successes, bt.failures)
        equiv = None
        if margin is not None:
            tost = newcombe_difference(
                tt.successes, tt.n_known, bt.successes, bt.n_known, confidence=1.0 - 2.0 * alpha
            )
            equiv = equivalence_by_interval(tost.low, tost.high, margin=margin, alpha=alpha)
        staged.append(_Staged(contrast, bt, tt, known, None, diff, fisher, equiv))

    measured = [s for s in staged if s.fisher is not None]
    family = tuple(s.contrast.name for s in measured)
    family_sources = _union(*(s.known for s in measured))
    pvalues = [s.fisher.p_value for s in measured if s.fisher is not None]
    holm = holm_bonferroni(pvalues, alpha=alpha) if pvalues else None
    adjusted = dict(zip(family, holm.adjusted, strict=True)) if holm else {}
    rejected = dict(zip(family, holm.reject, strict=True)) if holm else {}

    contrast_rows = []
    for st in staged:
        contrast, bt, tt, known = st.contrast, st.bt, st.tt, st.known
        reason, delta, exact, tost_result = st.reason, st.diff, st.fisher, st.equiv
        is_measured = delta is not None
        if not is_measured:
            verdict = "unknown"
        elif tost_result is None:
            verdict = "not assessed"
        else:
            verdict = "equivalent" if tost_result.equivalent else "not shown equivalent"
        sources = {
            "n_baseline": known,
            "n_treatment": known,
            "successes_baseline": known,
            "successes_treatment": known,
            "difference": known,
            "ci_low": known,
            "ci_high": known,
            "fisher_p": known,
            "holm_adjusted_p": family_sources,
            "holm_reject": family_sources,
            "equivalence": known,
        }
        contrast_rows.append(
            ContrastRow(
                name=contrast.name,
                baseline=contrast.baseline,
                treatment=contrast.treatment,
                isolates=contrast.isolates,
                status="measured" if is_measured else "unknown",
                reason=reason,
                n_baseline=bt.n_known,
                n_treatment=tt.n_known,
                successes_baseline=bt.successes if is_measured else None,
                successes_treatment=tt.successes if is_measured else None,
                difference=delta.difference if delta else None,
                ci_low=delta.low if delta else None,
                ci_high=delta.high if delta else None,
                fisher_p=exact.p_value if exact else None,
                holm_adjusted_p=adjusted.get(contrast.name),
                holm_reject=rejected.get(contrast.name),
                equivalence=verdict,
                equivalence_detail=tost_result.to_dict() if tost_result else None,
                sources=sources,
            )
        )

    return Report(
        experiment_id=collection.experiment_id,
        task_id=task_id,
        alpha=float(alpha),
        confidence=float(confidence),
        margin=None if margin is None else float(margin),
        baseline_arm=baseline_arm,
        arm_label="PILOT",
        arms=arm_rows,
        contrast_label="DERIVED",
        contrasts=tuple(contrast_rows),
        holm_family=family,
        notes=_notes(collection, arms, task_id, arm_rows, family),
    )


def _notes(
    collection: CollectionMetrics,
    arms: Mapping[str, ArmMetrics],
    task_id: str | None,
    arm_rows: tuple[ArmRow, ...],
    family: tuple[str, ...],
) -> tuple[str, ...]:
    notes = [
        _NOT_PREREGISTERED,
        "runs are treated as independent trials; the mixed-effects model with task random "
        "intercepts is not built (docs/backlog.md)",
        "no claim about agent behaviour is made",
    ]
    tasks = sorted({run.task_id for arm in arms.values() for run in arm.runs})
    if task_id is None and len(tasks) > 1:
        notes.append(
            f"pooled across {len(tasks)} tasks whose enforcement behaviour differs; "
            "a pooled difference can describe none of them (restrict with a task)"
        )
    missing = sum(row.unknown for row in arm_rows)
    if missing:
        notes.append(
            f"{missing} run(s) have no recorded outcome: unknown, excluded from every "
            "denominator, never counted as failures"
        )
    if not collection.is_balanced() and task_id is None:
        notes.append("arms ran different numbers of times; contrasts are weaker than they look")
    if len(family) == 0:
        notes.append("no contrast had a usable run in both arms, so no p-value is reported")
    return tuple(notes)


# --- rendering ------------------------------------------------------------


def _num(value: float | None, *, places: int = 4, sign: bool = False) -> str:
    if value is None:
        return "unknown"
    return f"{value:+.{places}f}" if sign else f"{value:.{places}f}"


def _p(value: float | None) -> str:
    if value is None:
        return "unknown"
    return "<0.0001" if value < 1e-4 else f"{value:.4f}"


def _interval(low: float | None, high: float | None, *, sign: bool = False) -> str:
    if low is None or high is None:
        return "unknown"
    return f"[{_num(low, sign=sign)}, {_num(high, sign=sign)}]"


def _ref(run_ids: tuple[str, ...]) -> str:
    """A compact, checkable reference to a set of run ids.

    The full list is in `to_dict()`; this carries the count, the ends of the
    sorted range and a digest of the whole set so two reports can be
    compared without printing hundreds of ids.
    """
    if not run_ids:
        return "0 runs"
    digest = hashlib.sha256("\n".join(run_ids).encode("utf-8")).hexdigest()[:12]
    ends = run_ids[0] if len(run_ids) == 1 else f"{run_ids[0]} .. {run_ids[-1]}"
    return f"{len(run_ids)} run(s) [{ends}] sha256:{digest}"


def _wrap(text: str, indent: str = "") -> list[str]:
    return textwrap.wrap(
        text, width=_WIDTH, initial_indent=indent, subsequent_indent=indent + "    "
    ) or [indent]


def render_text(report: Report) -> str:
    """Plain ASCII, at most 100 columns, safe for any console encoding."""
    pct = f"{report.confidence:.0%}"
    lines: list[str] = []
    scope = report.task_id if report.task_id is not None else "all tasks, pooled"
    lines.append(f"experiment: {report.experiment_id}   scope: {scope}")
    margin = "none" if report.margin is None else f"{report.margin:g}"
    lines += _wrap(
        f"assumptions (NOT preregistered): alpha={report.alpha:g} confidence={report.confidence:g} "
        f"margin={margin} baseline_arm={report.baseline_arm}"
    )
    lines.append("")

    lines.append(f"[{report.arm_label}] outcomes by arm (n counts known outcomes only)")
    head = f"{'arm':<5} {'n':>5} {'succ':>5} {'fail':>5} {'unk':>4} {'rate':>7} "
    head += f"{pct + ' Wilson':<17} {'vs ' + report.baseline_arm + ' (Newcombe)':<28}"
    lines.append(head.rstrip())
    for row in report.arms:
        vs = (
            "-"
            if row.arm == report.baseline_arm
            else _interval(row.diff_low, row.diff_high, sign=True)
        )
        if row.diff_vs_baseline is not None:
            vs = f"{_num(row.diff_vs_baseline, sign=True)} {vs}"
        elif row.arm != report.baseline_arm:
            vs = "unknown"
        lines.append(
            f"{row.arm:<5} {row.n:>5} {row.successes:>5} {row.failures:>5} {row.unknown:>4} "
            f"{_num(row.success_rate):>7} {_interval(row.ci_low, row.ci_high):<17} {vs}".rstrip()
        )
    lines.append("")

    lines.append(
        f"[{report.contrast_label}] primary contrasts, treatment - baseline "
        f"(Holm family m={len(report.holm_family)}, alpha={report.alpha:g})"
    )
    lines.append(
        f"{'contrast':<19} {'cmp':<5} {'n b/t':>7} {'diff':>7} {pct + ' Newcombe':<16} "
        f"{'Fisher':>7} {'Holm p':>7} {'rej':<4} equivalence"
    )
    for c in report.contrasts:
        reject = "-" if c.holm_reject is None else ("yes" if c.holm_reject else "no")
        lines.append(
            f"{c.name:<19} {c.baseline + '>' + c.treatment:<5} "
            f"{str(c.n_baseline) + '/' + str(c.n_treatment):>7} "
            f"{_num(c.difference, sign=True):>7} {_interval(c.ci_low, c.ci_high, sign=True):<16} "
            f"{_p(c.fisher_p):>7} {_p(c.holm_adjusted_p):>7} {reject:<4} {_SHORT_VERDICT[c.equivalence]}"
        )
        if c.reason:
            lines += _wrap(f"unknown: {c.reason}", indent="    ")
    if report.margin is not None:
        lines += _wrap(
            f"equivalence: 'equivalent' only if the {1 - 2 * report.alpha:.0%} interval lies "
            f"strictly inside +/-{report.margin:g}; 'not shown' is not evidence of a difference"
        )
    lines.append("")

    lines.append("sources (run ids; the full lists are in --json)")
    for row in report.arms:
        known, unknown = row.sources["n"], row.sources["unknown"]
        lines += _wrap(f"arm {row.arm}: known {_ref(known)}; unknown {_ref(unknown)}", indent="  ")
    for c in report.contrasts:
        lines += _wrap(f"{c.name}: {_ref(c.sources['difference'])}", indent="  ")
    if report.holm_family:
        lines += _wrap(
            f"holm adjustment: {_ref(report.contrasts[0].sources['holm_adjusted_p'])}", indent="  "
        )
    lines.append("")

    lines.append("notes")
    for note in report.notes:
        lines += _wrap(f"- {note}", indent="  ")
    return "\n".join(lines).encode("ascii", "backslashreplace").decode("ascii") + "\n"
