"""Unit tests for what the REAL CooperBench layout needed beyond the sample (backlog §54).

The first loader was written against a hand-built two-feature sample. Reading
the real dataset (github.com/cooperbench/CooperBench, `dataset/`) showed three
ways that sample under-described it, and each has a test here:

- a task has 2 to 12 features, not exactly 2, and every *pair* is a separate
  problem (30 tasks, 199 features, 652 pairs);
- the base repository is not shipped: `setup.sh` names an upstream URL and a
  pinned commit, so there must be a way to turn those back into files;
- a removed source line that begins with `-- ` renders as `--- ...` inside a
  hunk and must not be read as a file header.

Nothing here touches the network and nothing here is real CooperBench data.
The datasets built below are synthetic, shaped like the real layout
(`<repo>_task/task<id>/feature<N>/...`, a `subsets/` directory beside the
repos, a `setup.sh` with `BASE_COMMIT` and a clone line).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from causalmesh.tasks.cooperbench import (
    CooperBenchImportError,
    ImportOptions,
    feature_numbers,
    feature_pairs,
    import_dataset,
    import_dataset_report,
    import_task,
    touched_paths,
)
from causalmesh.tasks.cooperbench_base import (
    BaseRepoError,
    BaseSpec,
    base_files_for_paths,
    checkout_base_repo,
    parse_base_spec,
)

pytestmark = pytest.mark.unit

SHA = "0123456789abcdef0123456789abcdef01234567"

BASE_CALC = '''"""calc"""

OPS = {
    "add": lambda a, b: a + b,
}


def apply(name, a, b):
    return OPS[name](a, b)
'''


def _run(args: list[str], cwd: Path) -> str:
    # Bytes, decoded by hand: `text=True` would translate CRLF to LF and hide
    # exactly the line endings the CRLF tests are about.
    # autocrlf=false: Git for Windows defaults to `true`, which rewrites the tree these
    # patches are made from and then rejects its own diff on `git apply`.
    if args[0] == "git":
        args = ["git", "-c", "core.autocrlf=false", *args[1:]]
    done = subprocess.run(args, cwd=cwd, capture_output=True, check=True)
    return done.stdout.decode("utf-8")


def _init_repo(root: Path, files: dict[str, str | bytes]) -> str:
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q"], root)
    for relative, content in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    _run(["git", "add", "-A"], root)
    _run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base"],
        root,
    )
    return _run(["git", "rev-parse", "HEAD"], root).strip()


def _diff(repo: Path, edits: dict[str, str]) -> str:
    """A real `git diff` for `edits` against the committed state of `repo`."""
    for relative, content in edits.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content.encode("utf-8"))
    _run(["git", "add", "-N", "-A"], repo)
    text = _run(["git", "diff"], repo)
    # Drop the intent-to-add entries first: otherwise `checkout` restores the
    # new files as empty tracked files and they leak into the next diff.
    _run(["git", "reset", "-q"], repo)
    _run(["git", "checkout", "-q", "--", "."], repo)
    _run(["git", "clean", "-fdq"], repo)
    return text


def _make_dataset(root: Path, *, features: int = 3) -> tuple[Path, Path]:
    """A synthetic dataset with one task of `features` features, plus `subsets/`."""
    repo = root / "_origin"
    _init_repo(repo, {"src/calc.py": BASE_CALC})
    dataset = root / "dataset"
    task = dataset / "calc_task" / "task7"
    (dataset / "subsets").mkdir(parents=True)
    (dataset / "subsets" / "all.json").write_text("{}", encoding="utf-8")
    (dataset / "README.md").write_text("# not a repo\n", encoding="utf-8")
    task.mkdir(parents=True)
    (task / "setup.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    ops = {"sub": "a - b", "mul": "a * b", "div": "a / b"}
    for number, (name, expr) in zip(range(1, features + 1), ops.items(), strict=False):
        edited = BASE_CALC.replace(
            '    "add": lambda a, b: a + b,\n',
            f'    "add": lambda a, b: a + b,\n    "{name}": lambda a, b: {expr},\n',
        )
        feature = task / f"feature{number}"
        feature.mkdir()
        (feature / "feature.md").write_text(f"# {name}\n\nAdd {name}.\n", encoding="utf-8")
        # write_bytes: `write_text` would turn the patch's LF into CRLF on Windows.
        (feature / "feature.patch").write_bytes(
            _diff(repo, {"src/calc.py": edited}).encode("utf-8")
        )
        (feature / "tests.patch").write_bytes(
            _diff(
                repo,
                {f"tests/test_{name}.py": f"def test_{name}():\n    assert True\n"},
            ).encode("utf-8")
        )
    return dataset, task


class TestTouchedPathsInsideHunks:
    def test_a_removed_line_that_looks_like_a_file_header_is_not_a_path(self) -> None:
        # The removed line's content is "-- a SQL comment"; rendered in the
        # diff it is "--- a SQL comment", which matches the header pattern.
        diff = (
            "--- a/q.sql\n+++ b/q.sql\n@@ -1,3 +1,2 @@\n select 1;\n--- a SQL comment\n select 2;\n"
        )
        assert touched_paths(diff) == frozenset({"q.sql"})

    def test_an_added_line_that_looks_like_a_file_header_is_not_a_path(self) -> None:
        diff = "--- a/q.sql\n+++ b/q.sql\n@@ -1,1 +1,2 @@\n select 1;\n+++ b/fake.sql\n"
        assert touched_paths(diff) == frozenset({"q.sql"})

    def test_the_next_file_header_after_a_hunk_is_still_found(self) -> None:
        diff = (
            "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y\n"
            "\\ No newline at end of file\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        assert touched_paths(diff) == frozenset({"a.py", "b.py"})

    def test_a_form_feed_inside_a_line_does_not_miscount_the_hunk(self) -> None:
        # str.splitlines() would split on the form feed and shift every count.
        diff = "--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,2 @@\n \x0c\n--- not a header\n+new\n"
        assert touched_paths(diff) == frozenset({"a.py"})

    def test_wrong_hunk_counts_fall_back_to_reading_headers(self) -> None:
        diff = (
            "--- a/a.py\n+++ b/a.py\n@@ -1,9 +1,9 @@\n-x\n+y\n"
            "--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-x\n+y\n"
        )
        assert touched_paths(diff) == frozenset({"a.py", "b.py"})


class TestFeatureDiscovery:
    def test_a_task_can_have_more_than_two_features(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path, features=3)
        assert feature_numbers(task) == (1, 2, 3)
        assert feature_pairs(task) == [(1, 2), (1, 3), (2, 3)]

    def test_numbers_are_read_from_names_not_assumed_contiguous(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path, features=3)
        (task / "feature2").rename(task / "feature10")
        assert feature_numbers(task) == (1, 3, 10)


class TestImportingAPair:
    def test_a_later_pair_reads_its_own_feature_directories(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path, features=3)
        base = {"src/calc.py": BASE_CALC}
        imported = import_task(task, features=(1, 3), base_files=base)
        assert imported.feature_numbers == (1, 3)
        assert '"sub"' in imported.features["agent_a"].patch_text
        assert '"div"' in imported.features["agent_b"].patch_text
        assert '"mul"' not in imported.features["agent_b"].patch_text

    def test_the_default_pair_keeps_the_original_task_id(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        base = {"src/calc.py": BASE_CALC}
        assert import_task(task, base_files=base).definition.task_id == "cb_calc_task_task7"

    def test_other_pairs_get_distinct_task_ids(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        base = {"src/calc.py": BASE_CALC}
        ids = {
            import_task(task, features=pair, base_files=base).definition.task_id
            for pair in feature_pairs(task)
        }
        assert len(ids) == 3

    def test_a_missing_feature_directory_is_a_typed_error(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        with pytest.raises(CooperBenchImportError, match="feature1.*feature9"):
            import_task(task, features=(1, 9), base_files={"src/calc.py": BASE_CALC})

    def test_a_pair_needs_two_distinct_features(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        with pytest.raises(CooperBenchImportError, match="distinct"):
            import_task(task, features=(2, 2), base_files={"src/calc.py": BASE_CALC})

    def test_the_yaml_header_names_the_features_used(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        imported = import_task(task, features=(2, 3), base_files={"src/calc.py": BASE_CALC})
        written = imported.write_yaml(tmp_path / "t.yaml").read_text(encoding="utf-8")
        assert "feature2 -> agent_a, feature3 -> agent_b" in written


class TestLineEndingsSurvive:
    def test_a_crlf_file_is_patched_without_being_rewritten_to_lf(self, tmp_path: Path) -> None:
        crlf_base = "one\r\ntwo\r\nthree\r\n"
        repo = tmp_path / "origin"
        _init_repo(repo, {"data.txt": crlf_base})
        patch = _diff(repo, {"data.txt": "one\r\nTWO\r\nthree\r\n"})
        assert "\r" in patch

        task = tmp_path / "ds" / "r_task" / "task1"
        for number in (1, 2):
            feature = task / f"feature{number}"
            feature.mkdir(parents=True)
            (feature / "feature.patch").write_bytes(patch.encode("utf-8"))
        imported = import_task(task, base_files={"data.txt": crlf_base})
        content = imported.definition.scenario["agent_a"]["actions"][-1]["write"]["content"]
        assert content == "one\r\nTWO\r\nthree\r\n"

    def test_the_fixture_is_written_byte_for_byte(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        crlf = "a\r\nb\r\n"
        imported = import_task(task, base_files={"src/calc.py": BASE_CALC, "keep.txt": crlf})
        root = imported.write_fixture(tmp_path / "fx")
        assert (root / "keep.txt").read_bytes() == crlf.encode("utf-8")


class TestParseBaseSpec:
    def test_a_literal_clone_url(self) -> None:
        text = f'#!/bin/bash\nREPO_NAME="x"\nBASE_COMMIT="{SHA}"\n  git clone https://github.com/pallets/click "$REPO_NAME"\n'
        assert parse_base_spec(text) == BaseSpec("https://github.com/pallets/click", SHA)

    def test_a_dot_git_url_is_kept_as_written(self) -> None:
        text = f'BASE_COMMIT="{SHA}"\ngit clone https://github.com/stanfordnlp/dspy.git repo\n'
        assert parse_base_spec(text).repo_url == "https://github.com/stanfordnlp/dspy.git"

    def test_a_url_built_from_assignments(self) -> None:
        text = (
            'REPO_NAME="typst"\nREPO_OWNER="typst"\n'
            f'BASE_COMMIT="{SHA}"  # Base commit before PR\n'
            'git clone https://github.com/${REPO_OWNER}/${REPO_NAME} "$REPO_NAME"\n'
        )
        assert parse_base_spec(text).repo_url == "https://github.com/typst/typst"

    def test_a_commented_out_clone_is_ignored(self) -> None:
        text = (
            f'BASE_COMMIT="{SHA}"\n# git clone https://example.invalid/old r\n'
            "git clone https://github.com/a/b r\n"
        )
        assert parse_base_spec(text).repo_url == "https://github.com/a/b"

    def test_a_missing_commit_is_an_error_not_a_guess(self) -> None:
        with pytest.raises(BaseRepoError, match="BASE_COMMIT"):
            parse_base_spec("git clone https://github.com/a/b r\n")

    def test_a_short_commit_is_refused(self) -> None:
        with pytest.raises(BaseRepoError, match="BASE_COMMIT"):
            parse_base_spec('BASE_COMMIT="abc123"\ngit clone https://github.com/a/b r\n')

    def test_an_unresolved_variable_is_refused(self) -> None:
        text = f'BASE_COMMIT="{SHA}"\ngit clone https://github.com/${{OWNER}}/b r\n'
        with pytest.raises(BaseRepoError, match="unresolved"):
            parse_base_spec(text)

    def test_no_clone_line_is_refused(self) -> None:
        with pytest.raises(BaseRepoError, match="git clone"):
            parse_base_spec(f'BASE_COMMIT="{SHA}"\n')


@pytest.fixture
def origin(tmp_path: Path) -> tuple[BaseSpec, Path]:
    """A local upstream repository that allows the blobless by-SHA fetch the real one does."""
    root = tmp_path / "upstream"
    sha = _init_repo(
        root,
        {
            "src/calc.py": BASE_CALC,
            "README.md": "readme\r\n",
            "blob.bin": b"\xff\xfe\x00binary",
        },
    )
    for key, value in (
        ("uploadpack.allowFilter", "true"),
        ("uploadpack.allowAnySHA1InWant", "true"),
    ):
        _run(["git", "config", key, value], root)
    return BaseSpec(repo_url=root.as_uri(), base_commit=sha), tmp_path / "cache"


class TestFetchingBaseFiles:
    def test_fetches_only_the_requested_paths_byte_for_byte(
        self, origin: tuple[BaseSpec, Path]
    ) -> None:
        spec, cache = origin
        files = base_files_for_paths(spec, {"src/calc.py", "README.md"}, cache_dir=cache)
        assert files == {"src/calc.py": BASE_CALC, "README.md": "readme\r\n"}

    def test_a_path_the_commit_does_not_have_is_simply_absent(
        self, origin: tuple[BaseSpec, Path]
    ) -> None:
        spec, cache = origin
        files = base_files_for_paths(spec, {"src/calc.py", "src/new.py"}, cache_dir=cache)
        assert set(files) == {"src/calc.py"}

    def test_no_paths_is_an_empty_result(self, origin: tuple[BaseSpec, Path]) -> None:
        spec, cache = origin
        assert base_files_for_paths(spec, set(), cache_dir=cache) == {}

    def test_a_non_utf8_file_is_refused_rather_than_decoded_lossily(
        self, origin: tuple[BaseSpec, Path]
    ) -> None:
        spec, cache = origin
        with pytest.raises(BaseRepoError, match="UTF-8"):
            base_files_for_paths(spec, {"blob.bin"}, cache_dir=cache)

    def test_an_unreachable_remote_is_a_typed_error(self, tmp_path: Path) -> None:
        spec = BaseSpec(repo_url=(tmp_path / "does_not_exist").as_uri(), base_commit=SHA)
        with pytest.raises(BaseRepoError, match="could not fetch"):
            base_files_for_paths(spec, {"a"}, cache_dir=tmp_path / "cache")

    def test_the_second_read_of_a_commit_needs_no_remote(
        self, origin: tuple[BaseSpec, Path], tmp_path: Path
    ) -> None:
        import shutil

        spec, cache = origin
        base_files_for_paths(spec, {"src/calc.py"}, cache_dir=cache)
        shutil.rmtree(tmp_path / "upstream", ignore_errors=True)
        # The upstream is gone; the commit and the blob are already local.
        again = base_files_for_paths(spec, {"src/calc.py"}, cache_dir=cache)
        assert again == {"src/calc.py": BASE_CALC}

    def test_checkout_writes_the_whole_tree_without_a_dot_git(
        self, origin: tuple[BaseSpec, Path], tmp_path: Path
    ) -> None:
        spec, cache = origin
        destination = checkout_base_repo(spec, tmp_path / "tree", cache_dir=cache)
        assert (destination / "src" / "calc.py").read_text(encoding="utf-8") == BASE_CALC
        assert (destination / "blob.bin").read_bytes() == b"\xff\xfe\x00binary"
        assert not (destination / ".git").exists()


class TestImportDatasetOverRealShapedLayout:
    def test_non_task_entries_beside_the_repos_are_not_tasks(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path)
        imported = import_dataset(dataset, base_files_by_task={"calc_task/task7": _base()})
        assert [t.feature_numbers for t in imported] == [(1, 2)]

    def test_all_pairs_imports_every_pair_of_every_task(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path, features=3)
        imported = import_dataset(
            dataset, pairs="all", base_files_by_task={"calc_task/task7": _base()}
        )
        assert [t.feature_numbers for t in imported] == [(1, 2), (1, 3), (2, 3)]

    def test_an_unknown_pairs_mode_is_refused(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path)
        with pytest.raises(CooperBenchImportError, match="pairs"):
            import_dataset(dataset, pairs="some")

    def test_a_provider_supplies_base_files_per_pair(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path, features=3)
        seen: list[tuple[int, int]] = []

        def provider(task_dir: Path, pair: tuple[int, int]) -> dict[str, str]:
            seen.append(pair)
            return _base()

        import_dataset(dataset, pairs="all", base_files_provider=provider)
        assert seen == [(1, 2), (1, 3), (2, 3)]


def _base() -> dict[str, str]:
    return {"src/calc.py": BASE_CALC}


class TestImportReportAccountsForEveryPair:
    def test_successes_are_counted_with_their_contested_paths(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path, features=3)
        report = import_dataset_report(dataset, base_files_provider=lambda d, p: _base())
        assert (report.attempted, report.succeeded, report.failed) == (3, 3, 0)
        assert all(o.contested_paths == ("src/calc.py",) for o in report.outcomes)

    def test_a_base_repo_failure_is_recorded_with_its_stage_and_reason(
        self, tmp_path: Path
    ) -> None:
        dataset, _ = _make_dataset(tmp_path)

        def provider(task_dir: Path, pair: tuple[int, int]) -> dict[str, str]:
            raise BaseRepoError("could not fetch deadbeef from https://example.invalid/x")

        report = import_dataset_report(dataset, base_files_provider=provider)
        assert report.failed == 3
        assert {o.stage for o in report.outcomes} == {"base_repo"}
        assert "deadbeef" in report.outcomes[0].reason  # type: ignore[operator]

    def test_a_patch_that_does_not_apply_is_an_import_failure_not_a_crash(
        self, tmp_path: Path
    ) -> None:
        dataset, _ = _make_dataset(tmp_path)
        report = import_dataset_report(dataset, base_files_provider=lambda d, p: {})
        assert {o.stage for o in report.outcomes} == {"import"}
        assert all("did not apply" in (o.reason or "") for o in report.outcomes)

    def test_failures_are_counted_by_reason_and_nothing_is_dropped(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path)
        report = import_dataset_report(dataset, base_files_provider=lambda d, p: {})
        payload = report.to_dict()
        assert payload["attempted_pairs"] == len(payload["outcomes"]) == 3
        assert payload["imported_pairs"] == 0
        assert payload["tasks_with_at_least_one_imported_pair"] == 0
        assert sum(payload["failures_by_reason"].values()) == 3

    def test_an_unanticipated_exception_is_recorded_with_its_type(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path)

        def provider(task_dir: Path, pair: tuple[int, int]) -> dict[str, str]:
            raise RuntimeError("surprise")

        report = import_dataset_report(dataset, pairs="first", base_files_provider=provider)
        assert report.outcomes[0].stage == "unexpected"
        assert report.outcomes[0].reason == "RuntimeError: surprise"

    def test_tasks_are_kept_only_on_request(self, tmp_path: Path) -> None:
        dataset, _ = _make_dataset(tmp_path)
        lean = import_dataset_report(dataset, base_files_provider=lambda d, p: _base())
        kept = import_dataset_report(
            dataset, base_files_provider=lambda d, p: _base(), keep_tasks=True
        )
        assert lean.imported == []
        assert len(kept.imported) == 3


class TestHiddenTestHarnessGeneration:
    def test_the_generated_script_runs_each_features_test_files(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        imported = import_task(
            task,
            features=(1, 2),
            base_files=_base(),
            options=ImportOptions(hidden_tests="pytest"),
        )
        script = imported.run_tests_sh
        assert script is not None
        assert "tests/test_sub.py" in script
        assert "tests/test_mul.py" in script
        assert set(imported.extra_files) == {
            ".cooperbench/feature1_tests.patch",
            ".cooperbench/feature2_tests.patch",
        }
        assert "NOT CooperBench's own" in script

    def test_extra_files_land_in_the_fixture(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        imported = import_task(
            task, base_files=_base(), options=ImportOptions(hidden_tests="pytest")
        )
        root = imported.write_fixture(tmp_path / "fx")
        assert (root / ".cooperbench" / "feature1_tests.patch").is_file()

    def test_a_tests_patch_with_no_python_test_is_refused(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        (task / "feature1" / "tests.patch").write_bytes(
            b"--- /dev/null\n+++ b/notes.txt\n@@ -0,0 +1 @@\n+x\n"
        )
        with pytest.raises(CooperBenchImportError, match="no Python test file"):
            import_task(task, base_files=_base(), options=ImportOptions(hidden_tests="pytest"))

    def test_a_missing_tests_patch_is_refused(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        (task / "feature2" / "tests.patch").unlink()
        with pytest.raises(CooperBenchImportError, match="no tests.patch"):
            import_task(task, base_files=_base(), options=ImportOptions(hidden_tests="pytest"))

    def test_an_unknown_mode_is_refused(self, tmp_path: Path) -> None:
        _, task = _make_dataset(tmp_path)
        with pytest.raises(CooperBenchImportError, match="hidden_tests"):
            import_task(task, base_files=_base(), options=ImportOptions(hidden_tests="docker"))
