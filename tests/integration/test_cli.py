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
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from causalmesh.cli._output import Exit
from causalmesh.cli.main import app

pytestmark = [pytest.mark.integration]

REPO = Path(__file__).resolve().parents[2]

# The committed pilot. `data/raw/**` is gitignored, so a fresh clone and
# every CI checkout has no runs in it: a test that reads the pilot must say
# so rather than failing as though the CLI were broken.
#
# `tests/unit/test_tui.py` already guards this way. These did not, and CI's
# first run reported eighteen failures on Linux and macOS that were entirely
# "the evidence is not in the repository", which is true by design.
PILOT = REPO / "data" / "raw" / "pilot_landing"
needs_pilot = pytest.mark.skipif(
    not PILOT.is_dir(), reason="pilot artifacts are not in this checkout"
)
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


class TestCheckStdin:
    def test_stdin_json_matches_the_equivalent_flags(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        from_flags = invoke(
            "policy",
            "check",
            "--root",
            str(tmp_path),
            "--agent",
            "agent_b",
            "--kind",
            "path",
            "--name",
            "src/config.py",
            "--json",
        )
        from_stdin = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input='{"agent_id": "agent_b", "kind": "path", "name": "src/config.py"}',
        )
        assert from_flags.exit_code == from_stdin.exit_code == 1
        assert payload(from_flags) == payload(from_stdin)

    def test_stdin_allows_a_permitted_write(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input='{"agent_id": "agent_a", "kind": "path", "name": "src/config.py"}',
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["allowed"] is True

    def test_stdin_supports_spend_with_an_amount(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\n"
            "roles:\n"
            "  - agent_id: buyer\n"
            "    archetype: spender\n"
            "    allow: [api.example.com]\n"
            '    budget: { usd_total: "5.00" }\n',
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input='{"agent_id": "buyer", "kind": "spend", "name": "api.example.com", "amount": "1.00"}',
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["allowed"] is True

    def test_malformed_json_on_stdin_is_a_usage_error(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text("version: 1\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin"],
            input="not json at all",
        )
        assert result.exit_code == 2

    def test_a_json_object_missing_required_fields_is_a_usage_error(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text("version: 1\n", encoding="utf-8")
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin"],
            input='{"kind": "path"}',
        )
        assert result.exit_code == 2

    def test_an_explicit_null_name_is_a_usage_error_not_the_string_none(
        self, tmp_path: Path
    ) -> None:
        """A hook payload built by string templating may leave a field

        `null` instead of omitting it. `null` must fall back to the same
        default as an absent field (empty string for `name`), which the
        `if not name` guard then rejects with a clear usage error -- not
        silently coerce to the literal string "None" and check a resource
        that doesn't correspond to anything the caller intended.
        """
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin"],
            input='{"agent_id": "agent_a", "name": null}',
        )
        assert result.exit_code == 2

    def test_an_explicit_null_unit_falls_back_to_the_default(self, tmp_path: Path) -> None:
        """`unit: null` must fall back to `default_unit`, not become the

        literal string "None" passed through to `Resource.spend` as a
        bogus currency unit.
        """
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\n"
            "roles:\n"
            "  - agent_id: buyer\n"
            "    archetype: spender\n"
            "    allow: [api.example.com]\n"
            '    budget: { usd_total: "5.00" }\n',
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            ["policy", "check", "--root", str(tmp_path), "--stdin", "--json"],
            input=(
                '{"agent_id": "buyer", "kind": "spend", "name": "api.example.com", '
                '"amount": "1.00", "unit": null}'
            ),
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["resource"]["unit"] == "USD"

    def test_stdin_and_flags_together_prefers_flags(self, tmp_path: Path) -> None:
        """`--stdin` is a mode switch; when both are somehow given, the

        explicit CLI flags are what actually ran, not a silent merge with
        whatever also arrived on stdin.
        """
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles:\n  - agent_id: agent_a\n    owns: [src/config.py]\n",
            encoding="utf-8",
        )
        result = runner.invoke(
            app,
            [
                "policy",
                "check",
                "--root",
                str(tmp_path),
                "--stdin",
                "--json",
                "--agent",
                "agent_a",
                "--kind",
                "path",
                "--name",
                "src/config.py",
            ],
            input='{"agent_id": "agent_b", "kind": "path", "name": "src/config.py"}',
        )
        assert result.exit_code == 0, result.stdout
        assert payload(result)["allowed"] is True


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

    def test_the_imported_cooperbench_worked_example_is_in_the_suite(self) -> None:
        """backlog §54: the one worked example ships as a real task."""
        result = invoke("task", "list", "--root", str(REPO), "--json")
        assert result.exit_code == 0, result.stdout
        tasks = {task["task_id"]: task for task in payload(result)}
        assert "cb_tinyrepo_task1" in tasks
        assert tasks["cb_tinyrepo_task1"]["family"] == "cooperbench_import"


class TestImportCooperbench:
    """`causalmesh task import-cooperbench`, against the synthetic sample.

    Not the real CooperBench dataset — see
    `tests/fixtures/cooperbench_sample/README.md`. This proves the CLI
    surface itself, distinct from the loader's own unit tests.
    """

    SAMPLE = REPO / "tests" / "fixtures" / "cooperbench_sample"

    def test_imports_and_validates_from_the_cli(self, tmp_path: Path) -> None:
        # Runs against a scratch root so this test never writes into the
        # repository's real tasks/ or fixtures/ directories.
        root = tmp_path / "repo"
        for name in ("tasks", "fixtures", "pyproject.toml"):
            source = REPO / name
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

        result = invoke(
            "task",
            "import-cooperbench",
            str(self.SAMPLE / "dataset" / "tinyrepo" / "task1"),
            "--base-repo",
            str(self.SAMPLE / "base_repo"),
            "--task-id",
            "cb_cli_scratch_test",
            "--root",
            str(root),
            "--json",
        )
        assert result.exit_code == 0, result.stdout
        report = payload(result)
        assert report["task_id"] == "cb_cli_scratch_test"
        assert report["validation"]["valid"] is True
        assert (root / "tasks" / "cb_cli_scratch_test.yaml").is_file()
        assert (root / "fixtures" / "cb_cli_scratch_test").is_dir()

    def test_a_missing_base_repo_is_a_usage_error(self, tmp_path: Path) -> None:
        result = invoke(
            "task",
            "import-cooperbench",
            str(self.SAMPLE / "dataset" / "tinyrepo" / "task1"),
            "--base-repo",
            str(tmp_path / "does_not_exist"),
            "--root",
            str(REPO),
        )
        assert result.exit_code == 2

    def test_a_malformed_source_is_reported_not_crashed(self, tmp_path: Path) -> None:
        result = invoke(
            "task",
            "import-cooperbench",
            str(tmp_path),
            "--base-repo",
            str(self.SAMPLE / "base_repo"),
            "--root",
            str(REPO),
        )
        assert result.exit_code == Exit.ERROR


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


@pytest.mark.slow
class TestContractDiscovery:
    """`experiment run` auto-discovers `causalmesh.yaml` (docs/backlog.md:
    "The gate is installable but not yet installed by default").

    The repository's own `causalmesh.yaml` is real, so a run through it is
    the same discovery path `causalmesh serve` already uses (`Contract.find`),
    exercised for real rather than against a fixture contract.
    """

    def _run_artifact(self, experiment_id: str) -> dict:
        run_dir = next((REPO / "data" / "raw" / experiment_id).glob("*_r0000"))
        return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))

    def _cleanup(self, experiment_id: str) -> None:
        shutil.rmtree(REPO / "data" / "raw" / experiment_id, ignore_errors=True)
        shutil.rmtree(REPO / "data" / "work" / experiment_id, ignore_errors=True)

    def test_a_discovered_contract_installs_the_contract_gate(self) -> None:
        experiment_id = "exp_cd_on"
        self._cleanup(experiment_id)
        try:
            result = invoke(
                "experiment",
                "run",
                "--profile",
                "smoke",
                "--id",
                experiment_id,
                # The smoke profile plans 1 task x 4 arms; --limit 4 completes
                # the whole (small) plan so the run is not left PLANNED and
                # the CLI exits 0.
                "--limit",
                "4",
                "--root",
                str(REPO),
                "--json",
            )
            assert result.exit_code == 0, result.stdout

            artifact = self._run_artifact(experiment_id)
            assert artifact["provenance"]["contract_path"] == str(REPO / "causalmesh.yaml")
            # ContractGate reaches a verdict on every mutating call once
            # installed, contract or not — this is the fact that proves the
            # gate actually ran rather than just recording a path string.
            verdict_types = {event["event"]["event_type"] for event in artifact["chain"]}
            assert "POLICY_VERDICT" in verdict_types
        finally:
            self._cleanup(experiment_id)

    def test_no_contract_flag_skips_discovery_even_with_one_present(self) -> None:
        experiment_id = "exp_cd_off"
        self._cleanup(experiment_id)
        try:
            result = invoke(
                "experiment",
                "run",
                "--profile",
                "smoke",
                "--id",
                experiment_id,
                "--limit",
                "4",
                "--no-contract",
                "--root",
                str(REPO),
                "--json",
            )
            assert result.exit_code == 0, result.stdout

            artifact = self._run_artifact(experiment_id)
            assert "contract_path" not in artifact["provenance"]
            verdict_types = {event["event"]["event_type"] for event in artifact["chain"]}
            assert "POLICY_VERDICT" not in verdict_types
        finally:
            self._cleanup(experiment_id)


@needs_pilot
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


@needs_pilot
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


@needs_pilot
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
            return next(c for c in by_task[task] if c["name"] == "enforcement_benefit")[
                "success_delta"
            ]

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
        result = invoke("analyze", "--id", "pilot_landing", "--task", "nope", "--root", str(REPO))
        assert result.exit_code == 2

    def test_selecting_nothing_is_a_usage_error(self) -> None:
        result = invoke("analyze", "--root", str(REPO))
        assert result.exit_code == 2

    def test_edges_on_an_artifact_older_than_the_feature_reports_none(self) -> None:
        """The pilot predates edge population; that is a fact, not an error.

        `edges_for_run` treats a missing `edges` key as "none recorded"
        rather than raising, so an artifact from before this feature shipped
        still analyzes cleanly instead of failing.
        """
        result = invoke(
            "analyze", "--edges", "--id", "pilot_landing", "--root", str(REPO), "--json"
        )
        assert result.exit_code == 0, result.stdout
        report = payload(result)
        assert report["total_edges"] == 0
        assert report["total_runs"] == 24


@pytest.mark.slow
class TestAnalyzeEdgesEndToEnd:
    """A real contract-enforced run's denial produces a queryable edge.

    `experiment run`'s own contract discovery (`TestContractDiscovery` above)
    picks up the repository's `causalmesh.yaml`, whose roles don't overlap
    this task's `agent_a`/`agent_b` scenario, so it never refuses anything.
    Getting a real denial into a real run artifact needs a contract that
    actually names an owner — the same `execute_task` call
    `TestPolicyVerdictsOnTheChain` (in test_task_execution.py) uses — with
    the resulting artifact placed where `causalmesh analyze` looks for one,
    so the CLI's read path is what is actually being exercised.
    """

    def _cleanup(self, experiment_id: str) -> None:
        shutil.rmtree(REPO / "data" / "raw" / experiment_id, ignore_errors=True)
        shutil.rmtree(REPO / "data" / "work" / experiment_id, ignore_errors=True)

    def test_a_denied_write_appears_as_an_edge_through_analyze(self, tmp_path: Path) -> None:
        import asyncio

        from causalmesh.tasks import RunConfig, TaskDefinition, execute_task

        experiment_id = "exp_test_analyze_edges"
        self._cleanup(experiment_id)
        try:
            contract_path = tmp_path / "causalmesh.yaml"
            contract_path.write_text(
                "version: 1\n"
                "roles:\n"
                "  - agent_id: agent_a\n"
                "    owns: [src/handler.py]\n"
                "policy:\n"
                "  arm: C3\n",
                encoding="utf-8",
            )
            task = TaskDefinition.from_yaml(REPO / "tasks" / "schema_handler_widen.yaml")
            run_id = f"{experiment_id}_run0"
            result = asyncio.run(
                execute_task(
                    task,
                    RunConfig(
                        experiment_id=experiment_id,
                        run_id=run_id,
                        arm="C3",
                        master_seed=b"causalmesh-analyze-edges-cli-test",
                        contract_path=str(contract_path),
                    ),
                    workspace_root=tmp_path / "ws",
                    fixtures_root=REPO / "fixtures",
                )
            )

            run_dir = REPO / "data" / "raw" / experiment_id / run_id
            run_dir.mkdir(parents=True)
            artifact = {
                "arm": result.arm,
                "chain": result.records,
                "experiment_id": experiment_id,
                "result": result.to_dict(),
                "run_id": result.run_id,
                "task_id": result.task_id,
            }
            (run_dir / "run.json").write_text(json.dumps(artifact), encoding="utf-8")

            analyze_result = invoke(
                "analyze", "--edges", "--id", experiment_id, "--root", str(REPO), "--json"
            )
            assert analyze_result.exit_code == 0, analyze_result.stdout
            report = payload(analyze_result)
            assert report["total_edges"] >= 1
            edge = report["runs"][0]["edges"][0]
            assert edge["relationship"] == "REQUIRED"
        finally:
            self._cleanup(experiment_id)


@needs_pilot
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
