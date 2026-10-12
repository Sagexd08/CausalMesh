"""The report builder's gates: labels, required assumptions, unknown outcomes.

The CLI-level arithmetic is checked in `tests/integration/test_report_cli.py`.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from causalmesh.analysis.inference import InferenceError
from causalmesh.metrics.accounting import ArmMetrics, CollectionMetrics, RunMetrics
from causalmesh.reporting import (
    EMITTABLE_LABELS,
    LABELS,
    ReportError,
    build_report,
    render_text,
)

pytestmark = pytest.mark.unit


def _arm(arm: str, outcomes: list[bool | None]) -> ArmMetrics:
    runs = [
        RunMetrics(
            run_id=f"{arm}_{i}",
            arm=arm,
            task_id="t",
            coordination_bytes=0,
            coordination_tokens=0,
            events=0,
            denials=0,
            turns=0,
            succeeded=outcome,
            received_no_coordination=False,
        )
        for i, outcome in enumerate(outcomes)
    ]
    return ArmMetrics(arm=arm, runs=runs)


def _collection() -> CollectionMetrics:
    return CollectionMetrics(
        experiment_id="exp",
        arms={
            "C0": _arm("C0", [False, False, True, None]),
            "C2": _arm("C2", [True, True, True, False]),
        },
    )


def test_only_pilot_and_derived_are_emitted() -> None:
    assert set(EMITTABLE_LABELS) == {"PILOT", "DERIVED"}
    assert set(EMITTABLE_LABELS) < set(LABELS)
    report = build_report(_collection(), confidence=0.95, alpha=0.05)
    assert (report.arm_label, report.contrast_label) == ("PILOT", "DERIVED")


@pytest.mark.parametrize("label", ["CONFIRMATORY", "ANALYTICAL", "EXPLORATORY", "made_up"])
def test_a_report_cannot_be_given_a_gated_or_unknown_label(label: str) -> None:
    report = build_report(_collection(), confidence=0.95, alpha=0.05)
    with pytest.raises(ReportError):
        dataclasses.replace(report, contrast_label=label)


def test_assumptions_have_no_defaults() -> None:
    with pytest.raises(TypeError):
        build_report(_collection(), confidence=0.95)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        build_report(_collection(), alpha=0.05)  # type: ignore[call-arg]


def test_bad_assumptions_are_refused() -> None:
    for kwargs in (
        {"alpha": 0.0, "confidence": 0.95},
        {"alpha": 0.05, "confidence": 1.0},
        {"alpha": 0.05, "confidence": 0.95, "margin": 0.0},
        {"alpha": 0.5, "confidence": 0.95, "margin": 0.1},
    ):
        with pytest.raises(InferenceError):
            build_report(_collection(), **kwargs)  # type: ignore[arg-type]


def test_unknown_outcome_is_excluded_from_n_and_reported() -> None:
    report = build_report(_collection(), confidence=0.95, alpha=0.05)
    c0 = next(row for row in report.arms if row.arm == "C0")
    assert (c0.runs, c0.n, c0.successes, c0.failures, c0.unknown) == (4, 3, 1, 2, 1)
    assert c0.sources["unknown"] == ("C0_3",)


def test_a_contrast_without_both_arms_is_unknown() -> None:
    report = build_report(_collection(), confidence=0.95, alpha=0.05)
    by_name = {row.name: row for row in report.contrasts}
    # C1 and C3 are absent from the collection.
    for name in ("representation", "enforcement_benefit", "complete_system"):
        assert by_name[name].status == "unknown"
        assert by_name[name].difference is None and by_name[name].fisher_p is None
    assert by_name["information_benefit"].status == "measured"
    assert report.holm_family == ("information_benefit",)


def test_render_and_dict_are_ascii_json_and_reproducible() -> None:
    first = build_report(_collection(), confidence=0.95, alpha=0.05, margin=0.1)
    second = build_report(_collection(), confidence=0.95, alpha=0.05, margin=0.1)
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(
        second.to_dict(), sort_keys=True
    )
    text = render_text(first)
    assert text.isascii() and max(len(line) for line in text.splitlines()) <= 100
