"""Unit tests for the CooperBench loader (backlog §54).

Exercises `causalmesh.tasks.cooperbench` against the hand-built synthetic
sample at `tests/fixtures/cooperbench_sample/` — see that directory's
README for why it is synthetic and what it is standing in for. Nothing
here asserts anything about the real CooperBench dataset, which is not
vendored in this repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.tasks import TaskFamily, validate_structure
from causalmesh.tasks.cooperbench import (
    CooperBenchImportError,
    ImportOptions,
    import_dataset,
    import_task,
    touched_paths,
)

pytestmark = pytest.mark.unit

SAMPLE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "cooperbench_sample"
BASE_REPO = SAMPLE_ROOT / "base_repo"
TASK_DIR = SAMPLE_ROOT / "dataset" / "tinyrepo" / "task1"


def _base_files() -> dict[str, str]:
    return {
        path.relative_to(BASE_REPO).as_posix(): path.read_text(encoding="utf-8")
        for path in BASE_REPO.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


class TestTouchedPaths:
    def test_extracts_paths_from_diff_headers(self) -> None:
        diff = (
            "diff --git a/src/x.py b/src/x.py\n"
            "index 1234..5678 100644\n"
            "--- a/src/x.py\n"
            "+++ b/src/x.py\n"
            "@@ -1,1 +1,2 @@\n"
            " one\n"
            "+two\n"
        )
        assert touched_paths(diff) == frozenset({"src/x.py"})

    def test_multiple_files(self) -> None:
        diff = (
            "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        assert touched_paths(diff) == frozenset({"a.py", "b.py"})

    def test_dev_null_is_excluded(self) -> None:
        diff = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+content\n"
        assert touched_paths(diff) == frozenset({"new.py"})

    def test_empty_diff_touches_nothing(self) -> None:
        assert touched_paths("") == frozenset()

    def test_real_feature_patches_from_the_sample(self) -> None:
        feature1 = (TASK_DIR / "feature1" / "feature.patch").read_text(encoding="utf-8")
        feature2 = (TASK_DIR / "feature2" / "feature.patch").read_text(encoding="utf-8")
        assert touched_paths(feature1) == frozenset({"src/greeter.py"})
        assert touched_paths(feature2) == frozenset({"src/greeter.py", "src/utils.py"})


class TestImportTask:
    def test_requires_a_directory(self, tmp_path: Path) -> None:
        with pytest.raises(CooperBenchImportError):
            import_task(tmp_path / "does_not_exist")

    def test_requires_both_feature_directories(self, tmp_path: Path) -> None:
        (tmp_path / "feature1").mkdir()
        with pytest.raises(CooperBenchImportError, match="feature1.*feature2"):
            import_task(tmp_path)

    def test_imports_the_synthetic_sample(self) -> None:
        result = import_task(
            TASK_DIR,
            base_files=_base_files(),
            options=ImportOptions(task_id="cb_tinyrepo_task1_unit"),
        )
        assert result.definition.task_id == "cb_tinyrepo_task1_unit"
        assert result.definition.family == TaskFamily.COOPERBENCH_IMPORT
        assert result.repo_name == "tinyrepo"
        assert result.source_task_id == "task1"

    def test_discovers_the_contested_path_from_the_patches(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        # Both features' patches touch src/greeter.py; only feature2 also
        # touches src/utils.py alone.
        assert result.definition.contested_paths == frozenset({"src/greeter.py"})

    def test_ownership_excludes_the_contested_path(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        role_a = result.definition.role_for("agent_a")
        role_b = result.definition.role_for("agent_b")
        assert "src/greeter.py" not in role_a.owns
        assert "src/greeter.py" not in role_b.owns
        assert role_b.owns == frozenset({"src/utils.py"})

    def test_agent_b_depends_on_the_contested_path(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        role_b = result.definition.role_for("agent_b")
        assert "src/greeter.py" in role_b.depends_on

    def test_feature1_maps_to_agent_a_feature2_to_agent_b(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        assert set(result.features) == {"agent_a", "agent_b"}
        assert "formal" in result.features["agent_a"].patch_text
        assert "friendly" in result.features["agent_b"].patch_text

    def test_materialized_write_actions_carry_real_content_not_diff_text(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        agent_a_actions = result.definition.scenario["agent_a"]["actions"]
        writes = [a["write"] for a in agent_a_actions if "write" in a]
        assert writes, "expected at least one materialized write action"
        content = writes[0]["content"]
        assert "diff --git" not in content
        assert "formal" in content

    def test_default_task_id_is_derived_from_repo_and_source(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        assert result.definition.task_id == "cb_tinyrepo_task1"

    def test_divergence_is_not_fabricated_by_default(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        assert result.definition.success.divergence_file is None
        assert result.definition.success.divergence_marker is None

    def test_operator_supplied_divergence_is_honoured(self) -> None:
        result = import_task(
            TASK_DIR,
            base_files=_base_files(),
            options=ImportOptions(
                divergence_file="src/greeter.py",
                divergence_marker='"formal": "Good day"',
            ),
        )
        assert result.definition.success.divergence_file == "src/greeter.py"

    def test_test_runner_defaults_to_bash_run_tests_sh(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        assert result.definition.success.integration_test == ("bash", "run_tests.sh")

    def test_setup_and_run_tests_scripts_are_captured(self) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        assert result.setup_sh is not None
        assert result.run_tests_sh is not None
        assert "pytest" in result.run_tests_sh

    def test_produces_a_structurally_valid_task(self, tmp_path: Path) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        fixtures_root = tmp_path / "fixtures"
        result.write_fixture(fixtures_root / result.definition.fixture)
        report = validate_structure(result.definition, fixtures_root=fixtures_root)
        assert report.valid, [issue.to_dict() for issue in report.issues]


class TestWriteYamlRoundTrips:
    def test_written_yaml_loads_back_via_taskdefinition_from_yaml(self, tmp_path: Path) -> None:
        from causalmesh.tasks import TaskDefinition

        result = import_task(
            TASK_DIR, base_files=_base_files(), options=ImportOptions(task_id="cb_roundtrip")
        )
        yaml_path = result.write_yaml(tmp_path / "cb_roundtrip.yaml")
        reloaded = TaskDefinition.from_yaml(yaml_path)
        assert reloaded.task_id == "cb_roundtrip"
        assert reloaded.content_hash() == result.definition.content_hash()

    def test_write_fixture_writes_setup_and_test_scripts(self, tmp_path: Path) -> None:
        result = import_task(TASK_DIR, base_files=_base_files())
        fixture_dir = tmp_path / "fx"
        result.write_fixture(fixture_dir)
        assert (fixture_dir / "setup.sh").is_file()
        assert (fixture_dir / "run_tests.sh").is_file()
        assert (fixture_dir / "src" / "greeter.py").is_file()
        assert (fixture_dir / "tests" / "test_greeter.py").is_file()


class TestImportDataset:
    def test_imports_every_task_under_the_dataset_root(self) -> None:
        results = import_dataset(
            SAMPLE_ROOT / "dataset",
            base_files_by_task={
                "tinyrepo/task1": _base_files(),
            },
        )
        assert len(results) == 1
        assert results[0].repo_name == "tinyrepo"
        assert results[0].source_task_id == "task1"

    def test_requires_a_directory(self, tmp_path: Path) -> None:
        with pytest.raises(CooperBenchImportError):
            import_dataset(tmp_path / "nope")


class TestPatchDoesNotApplyCleanly:
    def test_raises_a_typed_error(self, tmp_path: Path) -> None:
        feature1 = tmp_path / "feature1"
        feature2 = tmp_path / "feature2"
        feature1.mkdir()
        feature2.mkdir()
        (feature1 / "feature.patch").write_text(
            "--- a/missing.py\n+++ b/missing.py\n@@ -1,3 +1,3 @@\n"
            "-line one\n-line two\n-line three\n+changed one\n+changed two\n+changed three\n",
            encoding="utf-8",
        )
        (feature2 / "feature.patch").write_text(
            "--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-x\n+y\n", encoding="utf-8"
        )
        with pytest.raises(CooperBenchImportError, match="did not apply cleanly"):
            import_task(tmp_path, base_files={})
