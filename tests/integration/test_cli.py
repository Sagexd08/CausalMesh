"""The command line, invoked (spec §62, §91).

§91 asks for a step to be exercised rather than asserted, and a CLI is
exactly the kind of component that type-checks while being unusable: a
wrong field name in a summary is invisible until someone reads the output
and believes it.

These tests therefore run real commands against real artifacts through
typer's runner, and assert on exit codes and the JSON payloads a script
would consume. The human-readable tables are deliberately not asserted on
word by word — that would pin the wording and make every future improvement
a test change.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.cli.main import app

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]
runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args))


def payload(result) -> dict | list:
    """Parse the JSON a `--json` invocation produced.

    Rich pretty-prints JSON to a width, so the output is re-parsed rather
    than compared as text: a line break inside a long hash is a rendering
    detail, not a difference in the data.
    """
    return json.loads(result.stdout)


class TestDoctor:
    def test_doctor_passes_in_a_real_checkout(self) -> None:
        result = invoke("doctor", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        report = payload(result)
        assert report["verdict"] in {"PASS", "WARN"}
        assert report["failed"] == 0

    def test_doctor_reports_the_unbuilt_subsystems(self) -> None:
        """The honest half of the health check.

        A CLI that offers commands without saying which ones have no
        implementation behind them leaves the user to discover the gaps by
        hitting them.
        """
        result = invoke("doctor", "--root", str(REPO), "--json")
        coverage = next(c for c in payload(result)["checks"] if c["check"] == "coverage")
        assert coverage["status"] == "WARN"
        assert "analysis" in coverage["detail"]

    def test_doctor_fails_outside_a_checkout(self, tmp_path: Path) -> None:
        result = invoke("doctor", "--root", str(tmp_path), "--json")
        assert result.exit_code == 1
        assert payload(result)["verdict"] == "FAIL"


class TestTask:
    def test_the_suite_validates(self) -> None:
        result = invoke("task", "validate", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        report = payload(result)
        assert report["valid"] is True
        assert report["tasks"] >= 2

    def test_list_reports_every_task_with_its_hash(self) -> None:
        result = invoke("task", "list", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        tasks = payload(result)
        ids = {task["task_id"] for task in tasks}
        assert {"schema_handler_widen", "concurrent_edit_collision"} <= ids
        # §33 pins the suite by hash; a task without one is not attributable.
        assert all(len(task["hash"]) == 64 for task in tasks)


class TestPlan:
    def test_the_smoke_plan_is_balanced_across_arms(self) -> None:
        result = invoke("experiment", "plan", "--profile", "smoke", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        plan = payload(result)
        assert plan["balanced"] is True
        assert set(plan["arms"]) == {"C0", "C1", "C2", "C3"}
        assert plan["runs"] == 4

    def test_the_confirmatory_profile_stays_gated(self) -> None:
        """§62 exit codes carry meaning: a refused gate is a usage error.

        The gate exists so confirmatory numbers cannot be produced by
        accident and quoted later as planned.
        """
        result = invoke("experiment", "plan", "--profile", "confirmatory", "--root", str(REPO))
        assert result.exit_code == 2

    def test_the_gate_opens_when_asked_explicitly(self) -> None:
        result = invoke(
            "experiment",
            "plan",
            "--profile",
            "confirmatory",
            "--allow-gated",
            "--root",
            str(REPO),
            "--json",
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["runs"] == 960

    def test_an_unknown_profile_is_a_usage_error(self) -> None:
        result = invoke("experiment", "plan", "--profile", "nonsense", "--root", str(REPO))
        assert result.exit_code == 2


class TestVerify:
    """Verification through the CLI, against the pilot artifacts on disk."""

    def test_the_pilot_chains_verify(self) -> None:
        result = invoke("verify", "--id", "pilot_landing", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        report = payload(result)
        assert report["runs"] == 24
        assert report["verified"] == 24
        assert report["valid"] is True

    def test_a_tampered_chain_is_refused(self, tmp_path: Path) -> None:
        """The mutation check: a verifier that cannot fail proves nothing.

        One byte of one event payload is changed in an exported copy. The
        raw data is never touched — the copy is what gets mutated.
        """
        source = next(
            (REPO / "data" / "raw" / "pilot_landing").glob("*C3*r0000"),
        )
        export = tmp_path / "run"
        export.mkdir()
        artifact = json.loads((source / "run.json").read_text(encoding="utf-8"))
        artifact["chain"][1]["event"]["payload"] = {"tampered": True}
        (export / "run.json").write_text(json.dumps(artifact), encoding="utf-8")

        result = invoke("verify", "--run", str(export), "--json")
        assert result.exit_code == 1
        assert payload(result)["verified"] == 0

    def test_an_untouched_export_verifies_with_no_repository(self, tmp_path: Path) -> None:
        """§82: an auditor with an export and nothing else can check it.

        `--run` takes a directory anywhere on disk, with no checkout, no
        index and no relay.
        """
        source = next((REPO / "data" / "raw" / "pilot_landing").glob("*C3*r0000"))
        export = tmp_path / "run"
        export.mkdir()
        (export / "run.json").write_text(
            (source / "run.json").read_text(encoding="utf-8"), encoding="utf-8"
        )

        result = invoke("verify", "--run", str(export), "--json")
        assert result.exit_code == 0, result.stdout
        assert payload(result)["verified"] == 1

    def test_selecting_nothing_is_a_usage_error(self) -> None:
        result = invoke("verify", "--root", str(REPO))
        assert result.exit_code == 2

    def test_an_unknown_experiment_is_a_usage_error(self) -> None:
        result = invoke("verify", "--id", "no_such_experiment", "--root", str(REPO))
        assert result.exit_code == 2


class TestStatus:
    def test_status_counts_successes_from_the_outcome(self) -> None:
        """Regression: success lives on `result.outcome.succeeded`.

        An earlier version read `result.success`, which does not exist, and
        so reported every arm as 0 passed while the runner reported real
        successes. A missing key must never read as a confident zero —
        that is the defect class recorded in docs/backlog.md.
        """
        result = invoke(
            "experiment", "status", "--id", "pilot_landing", "--root", str(REPO), "--json"
        )
        assert result.exit_code == 0, result.stdout
        per_arm = payload(result)["per_arm"]

        assert per_arm["C1"]["successes"] == 6
        assert per_arm["C2"]["successes"] == 6
        assert per_arm["C0"]["successes"] == 0
        # Nothing may be silently uncounted.
        assert all(bucket["unknown"] == 0 for bucket in per_arm.values())

    def test_status_reports_enforcement_and_cost(self) -> None:
        result = invoke(
            "experiment", "status", "--id", "pilot_landing", "--root", str(REPO), "--json"
        )
        per_arm = payload(result)["per_arm"]

        # C3 is the only arm that enforces, so it is the only arm that denies.
        assert per_arm["C3"]["denials"] > 0
        assert per_arm["C2"]["denials"] == 0
        # C0 spends nothing: no peer information reaches it at all.
        assert per_arm["C0"]["bytes"] == 0
        # C2 carries the same information as C3 for the same cost.
        assert per_arm["C2"]["bytes"] == per_arm["C3"]["bytes"]

class TestAnalyze:
    """`analyze` reports what the runs did, and says what it is not."""

    def test_the_pilot_analyses(self) -> None:
        result = invoke("analyze", "--id", "pilot_landing", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        report = payload(result)
        assert report["runs"] == 24
        assert report["balanced"] is True
        assert report["label"] == "PILOT"

    def test_arm_figures_match_the_published_results(self) -> None:
        result = invoke("analyze", "--id", "pilot_landing", "--root", str(REPO), "--json")
        arms = payload(result)["arms"]
        assert arms["C1"]["mean_coordination_bytes"] == 361.0
        assert arms["C2"]["mean_coordination_bytes"] == 196.0
        assert arms["C3"]["success_rate"] == 0.5
        assert arms["C3"]["denials"] == 3

    def test_contrasts_are_reported_per_task(self) -> None:
        """Pooling enforcement across these two tasks describes neither."""
        result = invoke("analyze", "--id", "pilot_landing", "--root", str(REPO), "--json")
        by_task = payload(result)["contrasts_by_task"]

        def enforcement(task: str) -> float:
            return next(
                c for c in by_task[task] if c["name"] == "enforcement_benefit"
            )["success_delta"]

        assert enforcement("schema_handler_widen") == 0.0
        assert enforcement("concurrent_edit_collision") == -1.0

    def test_a_single_task_can_be_selected(self) -> None:
        result = invoke(
            "analyze",
            "--id",
            "pilot_landing",
            "--task",
            "schema_handler_widen",
            "--root",
            str(REPO),
            "--json",
        )
        assert result.exit_code == 0, result.stdout
        assert list(payload(result)["contrasts_by_task"]) == ["schema_handler_widen"]

    def test_an_unknown_task_is_a_usage_error(self) -> None:
        result = invoke(
            "analyze", "--id", "pilot_landing", "--task", "nope", "--root", str(REPO)
        )
        assert result.exit_code == 2

    def test_selecting_nothing_is_a_usage_error(self) -> None:
        result = invoke("analyze", "--root", str(REPO))
        assert result.exit_code == 2

class TestManifestAndAudit:
    """Provenance through the CLI (§31, §83).

    Collections are built in `tmp_path` and passed with `--root`, so
    nothing here touches `data/raw/`, which §31 makes immutable.
    """

    @staticmethod
    def _checkout(tmp_path: Path) -> Path:
        """A directory that `find_root` will accept as a checkout."""
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        (tmp_path / "tasks").mkdir()
        (tmp_path / "fixtures").mkdir()
        run_dir = tmp_path / "data" / "raw" / "exp" / "exp__t__C0__r0000"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(
            json.dumps({"arm": "C0", "chain": [], "result": {"run_id": "r"}}),
            encoding="utf-8",
        )
        return tmp_path

    def test_audit_reports_a_collection_with_no_manifest(self, tmp_path: Path) -> None:
        """An unrecorded collection is not corrupt; it is unprovable."""
        root = self._checkout(tmp_path)
        result = invoke("audit", "--id", "exp", "--root", str(root), "--json")
        assert result.exit_code == 1
        report = payload(result)
        assert report["clean"] is False
        assert "no manifest recorded" in report["experiments"]["exp"]["findings"]

    def test_a_manifest_can_be_written_and_then_audits_clean(self, tmp_path: Path) -> None:
        root = self._checkout(tmp_path)
        written = invoke("manifest", "write", "--id", "exp", "--root", str(root), "--json")
        assert written.exit_code == 0, written.stdout
        assert payload(written)["artifacts"] == 1

        audited = invoke("audit", "--id", "exp", "--root", str(root), "--json")
        entry = payload(audited)["experiments"]["exp"]
        # The chain is empty in this fixture, so verification fails; the
        # manifest itself must still report the artifact as intact.
        assert entry["manifest"]["intact"] is True
        assert entry["manifest"]["checked"] == 1

    def test_audit_detects_a_mutated_artifact(self, tmp_path: Path) -> None:
        """§31: raw data is immutable, and a change to it is a finding."""
        root = self._checkout(tmp_path)
        invoke("manifest", "write", "--id", "exp", "--root", str(root))

        target = next((root / "data" / "raw" / "exp").rglob("run.json"))
        target.write_text(json.dumps({"tampered": True}), encoding="utf-8")

        result = invoke("audit", "--id", "exp", "--root", str(root), "--json")
        assert result.exit_code == 1
        findings = payload(result)["experiments"]["exp"]["findings"]
        assert any("changed since recording" in f for f in findings)

    def test_an_existing_manifest_is_not_silently_replaced(self, tmp_path: Path) -> None:
        """Overwriting would destroy the record that a state differed."""
        root = self._checkout(tmp_path)
        assert invoke("manifest", "write", "--id", "exp", "--root", str(root)).exit_code == 0
        second = invoke("manifest", "write", "--id", "exp", "--root", str(root))
        assert second.exit_code == 1
        forced = invoke("manifest", "write", "--id", "exp", "--root", str(root), "--force")
        assert forced.exit_code == 0

    def test_audit_reverifies_chains_rather_than_trusting_the_manifest(
        self, tmp_path: Path
    ) -> None:
        """A manifest says the bytes are unchanged, not that they were valid.

        Checking only the manifest would pass a collection whose chains
        never verified in the first place — which is this fixture.
        """
        root = self._checkout(tmp_path)
        invoke("manifest", "write", "--id", "exp", "--root", str(root))
        entry = payload(invoke("audit", "--id", "exp", "--root", str(root), "--json"))[
            "experiments"
        ]["exp"]
        assert entry["chains"]["runs"] == 1
        assert entry["chains"]["verified"] == 0
        assert any("failed verification" in f for f in entry["findings"])
