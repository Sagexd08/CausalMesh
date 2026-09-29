"""End-to-end CooperBench import: synthetic source -> loader -> fixture ->
§36 structural gate -> §37 sensitivity gate (backlog §54).

This proves the whole imported-task pipeline works using the hand-built
synthetic sample at `tests/fixtures/cooperbench_sample/` — see that
directory's README. It does **not** claim anything about real CooperBench
tasks: there is no vendored dataset and no network access to fetch one.

The §37 verdict this worked example actually produces is asserted honestly
rather than tuned toward "sensitive". `src/greeter.py` is a genuinely
contested path here (both synthetic features add a different key to the
same dict), and this project's contested-path merge
(`tasks/runner.py::_integrate_workspaces`) resolves a contested path to a
single last-writer rather than merging both features' changes — so the
integration test fails identically whichever arm's information the agent
had. That is a real, reportable finding about this specific synthetic
worked example (a task with a same-line-region conflict is not
distinguishable by the C0-vs-C2 information contrast, only by finer-
grained content merging that this platform does not attempt) — not a
defect in the loader, and not evidence about any real CooperBench task.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.tasks import (
    RunConfig,
    TaskDefinition,
    check_sensitivity,
    execute_task,
    validate_structure,
)
from causalmesh.tasks.cooperbench import ImportOptions, import_task

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
SAMPLE_ROOT = REPO / "tests" / "fixtures" / "cooperbench_sample"
BASE_REPO = SAMPLE_ROOT / "base_repo"
TASK_DIR = SAMPLE_ROOT / "dataset" / "tinyrepo" / "task1"
SEED = b"cooperbench-integration-test-seed"


def _base_files() -> dict[str, str]:
    return {
        path.relative_to(BASE_REPO).as_posix(): path.read_text(encoding="utf-8")
        for path in BASE_REPO.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


@pytest.fixture(scope="module")
def imported():
    return import_task(
        TASK_DIR,
        base_files=_base_files(),
        options=ImportOptions(task_id="cb_tinyrepo_task1_it"),
    )


@pytest.fixture(scope="module")
def materialized_fixtures_root(tmp_path_factory, imported) -> Path:
    root = tmp_path_factory.mktemp("cooperbench_fixtures")
    imported.write_fixture(root / imported.definition.fixture)
    return root


@pytest.fixture(scope="module")
def written_task_yaml(tmp_path_factory, imported) -> Path:
    root = tmp_path_factory.mktemp("cooperbench_tasks")
    return imported.write_yaml(root / f"{imported.definition.task_id}.yaml")


class TestTheLoaderProducesARunnablePipeline:
    def test_the_task_yaml_round_trips_through_from_yaml(
        self, written_task_yaml: Path, imported
    ) -> None:
        reloaded = TaskDefinition.from_yaml(written_task_yaml)
        assert reloaded.task_id == imported.definition.task_id
        assert reloaded.content_hash() == imported.definition.content_hash()

    def test_the_fixture_matches_what_the_scenario_expects(
        self, materialized_fixtures_root: Path, imported
    ) -> None:
        fixture_dir = materialized_fixtures_root / imported.definition.fixture
        assert (fixture_dir / "src" / "greeter.py").is_file()
        assert (fixture_dir / "src" / "utils.py").is_file()
        assert (fixture_dir / "tests" / "test_greeter.py").is_file()
        assert (fixture_dir / "run_tests.sh").is_file()


class TestStructuralGate:
    """§36: the imported task must be well-formed before anything runs it."""

    def test_it_passes_validate_structure(self, materialized_fixtures_root: Path, imported) -> None:
        report = validate_structure(imported.definition, fixtures_root=materialized_fixtures_root)
        assert report.valid, [issue.to_dict() for issue in report.issues]

    def test_the_contested_path_matches_what_the_scenario_actually_contests(self, imported) -> None:
        # validate_structure's own contention_mismatch rule would catch a
        # disagreement here; this test makes the specific claim explicit.
        assert imported.definition.contested_paths == frozenset({"src/greeter.py"})


class TestRealExecution:
    """The imported task actually runs, under the real §71/§79 runner."""

    async def test_c0_and_c2_both_execute_without_error(
        self, materialized_fixtures_root: Path, imported, tmp_path: Path
    ) -> None:
        for arm in ("C0", "C2"):
            result = await execute_task(
                imported.definition,
                RunConfig(
                    experiment_id="cooperbench_it",
                    run_id=f"cooperbench_it_{arm}",
                    arm=arm,
                    master_seed=SEED,
                ),
                workspace_root=tmp_path / arm,
                fixtures_root=materialized_fixtures_root,
            )
            assert result.error is None, f"{arm}: run raised {result.error}"
            # A real chain was produced and verifies offline, the same
            # evidence bar every other task in this suite is held to.
            from causalmesh.crypto.keys import KeyPair, PublicKeyRing
            from causalmesh.verifier import verify_chain

            agents = {r["event"]["identity"]["agent_id"] for r in result.records}
            ring = PublicKeyRing.from_keypairs({a: KeyPair.derive(SEED, a) for a in agents})
            report = verify_chain(result.records, ring)
            assert report.valid, f"{arm}: {report.summary()}"


class TestQualityGate:
    """§37: sensitivity is demonstrated by running, not asserted — and its
    real verdict is reported honestly, whatever it is."""

    async def test_the_gate_runs_and_reports_a_real_verdict(
        self, materialized_fixtures_root: Path, imported, tmp_path: Path
    ) -> None:
        report = await check_sensitivity(
            imported.definition,
            workspace_root=tmp_path / "gate",
            fixtures_root=materialized_fixtures_root,
            master_seed=SEED,
            repetitions=1,
        )
        # This synthetic worked example is NOT coordination-sensitive under
        # this platform's winner-take-all contested-path merge: both
        # synthetic features edit the same dict in src/greeter.py, so
        # whichever agent's write lands last, the other's key is lost
        # regardless of whether the second agent was informed. That is the
        # real, reportable verdict for *this* worked example — recorded
        # here rather than tuned toward "sensitive". See this module's
        # docstring and docs/backlog.md, "CooperBench import (§54)".
        assert report.isolated_successes == 0
        assert report.informed_successes == 0
        assert report.sensitive is False
        assert "indistinguishable" in report.detail
