"""`causalmesh report`, run as a subprocess against a synthetic collection.

The collection is built in `tmp_path` in the on-disk shape
`metrics.accounting.collect` reads (`<root>/data/raw/<experiment>/<run>/run.json`
with `arm`, and `result.run_id`, `result.task_id`, `result.outcome.succeeded`),
so nothing depends on `data/raw`, which is not in a fresh clone.

Expected numbers are derived by hand in comments. They say nothing about agent
behaviour: the collection is invented to exercise the arithmetic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]


def _write_run(
    experiment: Path, arm: str, index: int, *, succeeded: bool | None, task: str = "t1"
) -> None:
    run_id = f"{experiment.name}__{task}__{arm}__r{index:04d}"
    run_dir = experiment / run_id
    run_dir.mkdir(parents=True)
    result: dict = {"run_id": run_id, "task_id": task}
    if succeeded is not None:
        result["outcome"] = {"succeeded": succeeded}
    (run_dir / "run.json").write_text(json.dumps({"arm": arm, "result": result}), encoding="utf-8")


def _checkout(root: Path) -> Path:
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    (root / "tasks").mkdir()
    (root / "fixtures").mkdir()
    return root


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Four arms, ten known outcomes each, plus two unrecorded in C2.

    successes: C0 2/10, C1 8/10, C2 8/10 (+2 with no outcome), C3 4/10.
    """
    _checkout(tmp_path)
    experiment = tmp_path / "data" / "raw" / "exp"
    index = 0
    for arm, successes in (("C0", 2), ("C1", 8), ("C2", 8), ("C3", 4)):
        for i in range(10):
            _write_run(experiment, arm, index, succeeded=i < successes)
            index += 1
    for _ in range(2):
        _write_run(experiment, "C2", index, succeeded=None)
        index += 1
    return tmp_path


def run_report(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO / "src"),
        "PYTHONIOENCODING": "utf-8",
        "NO_COLOR": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "causalmesh", "report", "--root", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
    )


BASE = ("--id", "exp", "--alpha", "0.10", "--confidence", "0.95")


def payload(root: Path, *extra: str) -> dict:
    done = run_report(root, *BASE, *extra, "--json")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def contrast(report: dict, name: str) -> dict:
    return next(r for r in report["tables"]["contrasts"]["rows"] if r["name"] == name)


class TestReportCli:
    def test_counts_exclude_unknown_outcomes_and_report_them(self, root: Path) -> None:
        report = payload(root)
        arms = {r["arm"]: r for r in report["tables"]["arms"]["rows"]}
        # C2 has 12 runs: 10 with an outcome (8 pass, 2 fail), 2 with none.
        assert arms["C2"]["runs"] == 12
        assert (arms["C2"]["n"], arms["C2"]["successes"], arms["C2"]["failures"]) == (10, 8, 2)
        assert arms["C2"]["unknown"] == 2
        assert arms["C2"]["success_rate"] == pytest.approx(0.8)
        # The two unrecorded runs are named as unknown, not as failures.
        assert len(arms["C2"]["sources"]["unknown"]) == 2
        assert len(arms["C2"]["sources"]["n"]) == 10

    def test_the_planned_contrast_arithmetic(self, root: Path) -> None:
        report = payload(root)

        # information_benefit C0 -> C2: 8/10 against 2/10.
        # Fisher [[8,2],[2,8]]: margins all 10, n = 20, P(x) = C(10,x)^2 / 184756.
        # Observed x = 8 has 45^2 = 2025; x in {0, 1, 2, 8, 9, 10} weigh
        # 1, 100, 2025, 2025, 100, 1 = 4252, so p = 4252 / 184756 = 0.02301.
        info = contrast(report, "information_benefit")
        assert info["status"] == "measured"
        assert info["difference"] == pytest.approx(0.6)
        assert info["fisher_p"] == pytest.approx(4252 / 184756)

        # representation C1 -> C2: 8/10 against 8/10, difference 0, p = 1.
        rep = contrast(report, "representation")
        assert rep["difference"] == pytest.approx(0.0)
        assert rep["fisher_p"] == pytest.approx(1.0)

        # enforcement_benefit C2 -> C3: 4/10 against 8/10, difference -0.4.
        # Fisher [[4,6],[8,2]]: c1 = 12, n = 20, total C(20,12) = 125970;
        # x = 2..10 weigh 45, 1200, 9450, 30240, 44100, 30240, 9450, 1200, 45.
        # Observed x = 4 has 9450; x in {2, 3, 4, 8, 9, 10} are no more probable:
        # (45 + 1200 + 9450 + 9450 + 1200 + 45) / 125970 = 21390 / 125970 = 0.1698.
        enf = contrast(report, "enforcement_benefit")
        assert enf["difference"] == pytest.approx(-0.4)
        assert enf["fisher_p"] == pytest.approx(21390 / 125970)

        # complete_system C1 -> C3 has the same counts as C2 -> C3 (C1 and C2
        # are both 8/10), so the same difference and p.
        assert contrast(report, "complete_system")["fisher_p"] == pytest.approx(21390 / 125970)

    def test_holm_adjustment_across_the_four_contrasts(self, root: Path) -> None:
        # Raw p ascending: 0.02301 (info), 0.1698 (enf), 0.1698 (complete), 1.0 (rep).
        # Multipliers 4, 3, 2, 1: 0.09206, 0.50941, 0.33960 -> 0.50941 (monotone), 1.0.
        # At alpha = 0.10 only information_benefit is rejected.
        report = payload(root)
        assert set(report["tables"]["contrasts"]["holm_family"]) == {
            "information_benefit",
            "representation",
            "enforcement_benefit",
            "complete_system",
        }
        assert contrast(report, "information_benefit")["holm_adjusted_p"] == pytest.approx(
            4 * 4252 / 184756
        )
        assert contrast(report, "information_benefit")["holm_reject"] is True
        assert contrast(report, "enforcement_benefit")["holm_adjusted_p"] == pytest.approx(
            3 * 21390 / 125970
        )
        assert contrast(report, "enforcement_benefit")["holm_reject"] is False
        assert contrast(report, "representation")["holm_adjusted_p"] == pytest.approx(1.0)

    def test_labels_assumptions_and_sources_are_on_the_report(self, root: Path) -> None:
        report = payload(root, "--margin", "0.10")
        assert report["tables"]["arms"]["label"] == "PILOT"
        assert report["tables"]["contrasts"]["label"] == "DERIVED"
        assumptions = report["assumptions"]
        assert assumptions["alpha"] == 0.10 and assumptions["confidence"] == 0.95
        assert assumptions["margin"] == 0.10
        assert assumptions["preregistered"] is False
        every_run = {
            run_id for r in report["tables"]["arms"]["rows"] for run_id in r["sources"]["n"]
        }
        for row in report["tables"]["contrasts"]["rows"]:
            assert set(row["sources"]["difference"]) <= every_run
            assert row["sources"]["fisher_p"] and row["sources"]["holm_adjusted_p"]
            # Every number the row carries has a source entry.
            for name in ("difference", "ci_low", "ci_high", "fisher_p", "holm_adjusted_p"):
                assert name in row["sources"]

    def test_an_interval_far_wider_than_the_margin_is_not_equivalent(self, root: Path) -> None:
        # Ten runs per arm cannot show equivalence within +/-0.10.
        report = payload(root, "--margin", "0.10")
        rep = contrast(report, "representation")
        assert rep["equivalence"] == "not shown equivalent"
        assert rep["equivalence_detail"]["equivalent"] is False

    def test_no_margin_means_equivalence_is_not_assessed(self, root: Path) -> None:
        assert contrast(payload(root), "representation")["equivalence"] == "not assessed"

    def test_the_output_is_reproducible_and_carries_no_paths(self, root: Path) -> None:
        first = run_report(root, *BASE, "--json").stdout
        second = run_report(root, *BASE, "--json").stdout
        assert first == second
        assert str(root) not in first
        assert str(root).replace("\\", "/") not in first

    def test_text_output_is_ascii_and_within_100_columns(self, root: Path) -> None:
        done = run_report(root, *BASE, "--margin", "0.10")
        assert done.returncode == 0, done.stderr
        assert done.stdout.isascii()
        assert max(len(line) for line in done.stdout.splitlines()) <= 100
        assert "[PILOT]" in done.stdout and "[DERIVED]" in done.stdout
        assert "NOT preregistered" in done.stdout

    def test_a_contrast_with_no_usable_run_is_unknown_not_zero(self, tmp_path: Path) -> None:
        _checkout(tmp_path)
        experiment = tmp_path / "data" / "raw" / "exp"
        for i in range(3):
            _write_run(experiment, "C0", i, succeeded=None)  # never recorded
            _write_run(experiment, "C2", 10 + i, succeeded=True)
        report = payload(tmp_path)
        info = contrast(report, "information_benefit")
        assert info["status"] == "unknown"
        for key in ("difference", "ci_low", "ci_high", "fisher_p", "holm_adjusted_p"):
            assert info[key] is None
        assert info["n_baseline"] == 0 and info["n_treatment"] == 3
        assert "C0" in info["reason"]
        # No contrast was measurable, so no Holm family exists.
        assert report["tables"]["contrasts"]["holm_family"] == []
        arms = {r["arm"]: r for r in report["tables"]["arms"]["rows"]}
        assert arms["C0"]["success_rate"] is None and arms["C0"]["unknown"] == 3

    def test_task_filter_restricts_the_collection(self, tmp_path: Path) -> None:
        _checkout(tmp_path)
        experiment = tmp_path / "data" / "raw" / "exp"
        index = 0
        for task, passes in (("t1", True), ("t2", False)):
            for arm in ("C0", "C1", "C2", "C3"):
                for _ in range(3):
                    _write_run(experiment, arm, index, succeeded=passes, task=task)
                    index += 1
        pooled = payload(tmp_path)
        assert any("pooled" in note for note in pooled["notes"])
        only = payload(tmp_path, "--task", "t1")
        assert only["task_id"] == "t1"
        assert {r["arm"]: r["n"] for r in only["tables"]["arms"]["rows"]} == {
            "C0": 3,
            "C1": 3,
            "C2": 3,
            "C3": 3,
        }
        assert all(r["success_rate"] == 1.0 for r in only["tables"]["arms"]["rows"])


class TestReportUsage:
    @pytest.mark.parametrize(
        "args",
        [
            ("--id", "exp", "--confidence", "0.95"),  # no --alpha
            ("--id", "exp", "--alpha", "0.05"),  # no --confidence
            ("--id", "nope", "--alpha", "0.05", "--confidence", "0.95"),  # unknown experiment
            ("--id", "exp", "--alpha", "1.5", "--confidence", "0.95"),
            ("--id", "exp", "--alpha", "0.05", "--confidence", "0"),
            ("--id", "exp", "--alpha", "0.6", "--confidence", "0.95", "--margin", "0.1"),
            ("--id", "exp", "--alpha", "0.05", "--confidence", "0.95", "--margin", "0"),
            ("--id", "exp", "--alpha", "0.05", "--confidence", "0.95", "--task", "nope"),
            ("--id", "exp", "--alpha", "0.05", "--confidence", "0.95", "--baseline-arm", "C9"),
            ("--alpha", "0.05", "--confidence", "0.95"),  # nothing selected
        ],
    )
    def test_bad_invocations_exit_2(self, root: Path, args: tuple[str, ...]) -> None:
        done = run_report(root, *args)
        assert done.returncode == 2, (args, done.stdout, done.stderr)

    def test_latest_selects_the_newest_experiment(self, root: Path) -> None:
        done = run_report(root, "--latest", "--alpha", "0.05", "--confidence", "0.95", "--json")
        assert done.returncode == 0, done.stderr
        assert json.loads(done.stdout)["experiment_id"] == "exp"

    def test_an_experiment_with_no_runs_is_an_error_not_a_zero(self, tmp_path: Path) -> None:
        _checkout(tmp_path)
        (tmp_path / "data" / "raw" / "empty").mkdir(parents=True)
        done = run_report(tmp_path, "--id", "empty", "--alpha", "0.05", "--confidence", "0.95")
        assert done.returncode == 3
