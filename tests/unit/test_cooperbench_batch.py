"""Unit tests for the CooperBench batch importer's pure logic (backlog section 54).

Nothing here touches the network or the real dataset. The base-repo
resolver is exercised against a throwaway local git repository, and the
oracle against hand-built strings.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from causalmesh.tasks.cooperbench import CooperBenchImportError
from causalmesh.tasks.cooperbench_batch import (
    BINARY,
    BaseResolutionError,
    BaseSpec,
    BatchOptions,
    GitBaseResolver,
    PairKey,
    check_checkout_line_endings,
    discover_pairs,
    expected_digests,
    line_digest,
    parse_base_spec,
    summarize,
    verifier_source,
)

pytestmark = pytest.mark.unit

SHA = "a" * 40


def _task_dir(root: Path, repo: str, task: str, features: int) -> Path:
    task_dir = root / "dataset" / repo / task
    for number in range(1, features + 1):
        feature = task_dir / f"feature{number}"
        feature.mkdir(parents=True)
        (feature / "feature.patch").write_text("", encoding="utf-8")
    return task_dir


class TestParseBaseSpec:
    def test_dockerfile_gives_url_and_commit(self, tmp_path: Path) -> None:
        task = _task_dir(tmp_path, "x_task", "task1", 2)
        (task / "Dockerfile").write_text(
            "FROM python:3.11\n"
            f"RUN git clone https://github.com/acme/widget.git repo && \\\n"
            f"    cd repo && \\\n    git checkout {SHA}\n",
            encoding="utf-8",
        )
        spec = parse_base_spec(task)
        assert spec == BaseSpec("https://github.com/acme/widget", SHA)

    def test_setup_sh_with_shell_variables_is_the_fallback(self, tmp_path: Path) -> None:
        task = _task_dir(tmp_path, "x_task", "task1", 2)
        (task / "setup.sh").write_text(
            'REPO_NAME="widget"\nREPO_OWNER="acme"\n'
            f'BASE_COMMIT="{SHA}"  # a comment\n'
            'git clone https://github.com/${REPO_OWNER}/${REPO_NAME} "$REPO_NAME"\n',
            encoding="utf-8",
        )
        assert parse_base_spec(task) == BaseSpec("https://github.com/acme/widget", SHA)

    def test_nothing_to_read_is_a_named_error_not_a_guess(self, tmp_path: Path) -> None:
        task = _task_dir(tmp_path, "x_task", "task1", 2)
        with pytest.raises(BaseResolutionError, match="no repository URL"):
            parse_base_spec(task)


class TestDiscoverPairs:
    def _options(self, root: Path, **kwargs) -> BatchOptions:
        return BatchOptions(dataset_dir=root, output_dir=root / "out", **kwargs)

    def test_every_unordered_pair_of_every_task(self, tmp_path: Path) -> None:
        _task_dir(tmp_path, "a_task", "task1", 4)
        _task_dir(tmp_path, "a_task", "task2", 2)
        _task_dir(tmp_path, "b_task", "task9", 3)
        pairs = discover_pairs(self._options(tmp_path))
        assert len(pairs) == 6 + 1 + 3
        assert all(p.first < p.second for p in pairs)
        assert len({p.pair_id for p in pairs}) == len(pairs)

    def test_features_sort_numerically_not_lexically(self, tmp_path: Path) -> None:
        _task_dir(tmp_path, "a_task", "task1", 11)
        firsts_seconds = {(p.first, p.second) for p in discover_pairs(self._options(tmp_path))}
        assert (2, 10) in firsts_seconds and (10, 11) in firsts_seconds
        assert len(firsts_seconds) == 55

    def test_filters_and_limit(self, tmp_path: Path) -> None:
        _task_dir(tmp_path, "a_task", "task1", 3)
        _task_dir(tmp_path, "b_task", "task2", 3)
        only_b = discover_pairs(self._options(tmp_path, only_repos=frozenset({"b_task"})))
        assert {p.repo for p in only_b} == {"b_task"}
        assert len(discover_pairs(self._options(tmp_path, max_pairs=2))) == 2
        only_task = discover_pairs(self._options(tmp_path, only_tasks=frozenset({"task2"})))
        assert {p.task for p in only_task} == {"task2"}

    def test_a_missing_dataset_directory_is_an_error(self, tmp_path: Path) -> None:
        with pytest.raises(CooperBenchImportError):
            discover_pairs(self._options(tmp_path / "nope"))

    def test_task_ids_satisfy_the_task_definition_rule(self) -> None:
        key = PairKey("pallets_jinja_task", "task1621", 1, 6)
        assert key.task_id == "cb_pallets_jinja_task1621_f1_f6"
        assert key.task_id.replace("_", "").isalnum()


class TestOracle:
    def test_digest_ignores_order_carriage_returns_blank_lines_and_trailing_space(self) -> None:
        assert line_digest("a\nb\nc\n") == line_digest("c\r\nb  \r\n\r\na")

    def test_digest_notices_a_changed_or_missing_or_duplicated_line(self) -> None:
        base = line_digest("a\nb\nc\n")
        assert line_digest("a\nb\nd\n") != base
        assert line_digest("a\nb\n") != base
        assert line_digest("a\nb\nc\nc\n") != base

    def test_expected_is_base_plus_both_features_changes(self) -> None:
        base = {"f.py": "one\ntwo\nthree\n"}
        a = {"f.py": "ONE\ntwo\nthree\n"}
        b = {"f.py": "one\ntwo\nTHREE\n"}
        expected, skipped = expected_digests(base, a, b, {"f.py"}, {"f.py"})
        assert skipped == []
        assert expected["f.py"] == line_digest("ONE\ntwo\nTHREE\n")
        # Either feature alone is not the expectation.
        assert expected["f.py"] != line_digest(a["f.py"])
        assert expected["f.py"] != line_digest(b["f.py"])

    def test_a_path_only_one_feature_touches_expects_that_features_version(self) -> None:
        base = {"f.py": "one\n"}
        a = {"f.py": "one\nextra\n"}
        expected, _ = expected_digests(base, a, {}, {"f.py"}, set())
        assert expected["f.py"] == line_digest(a["f.py"])

    def test_a_created_file_has_an_empty_base(self) -> None:
        expected, _ = expected_digests({}, {"new.py": "x\n"}, {}, {"new.py"}, set())
        assert expected["new.py"] == line_digest("x\n")

    def test_a_path_a_patch_deleted_is_reported_not_checked(self) -> None:
        expected, skipped = expected_digests(
            {"gone.py": "x\n"}, {}, {"b.py": "y\n"}, {"gone.py"}, {"b.py"}
        )
        assert skipped == ["gone.py"]
        assert "gone.py" not in expected and "b.py" in expected

    def test_the_shipped_verifier_agrees_with_the_importers_digest(self, tmp_path: Path) -> None:
        import json

        (tmp_path / "cb_verify.py").write_text(verifier_source(), encoding="utf-8")
        (tmp_path / "f.py").write_bytes(b"c\r\nb\r\na\r\n")
        good = {"paths": {"f.py": line_digest("a\nb\nc\n")}}
        (tmp_path / "cb_expected.json").write_text(json.dumps(good), encoding="utf-8")

        def run() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, "cb_verify.py"],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                check=False,
            )

        passing = run()
        assert passing.returncode == 0, passing.stdout
        (tmp_path / "f.py").write_text("a\nb\nDIFFERENT\n", encoding="utf-8")
        failing = run()
        assert failing.returncode == 1
        assert "f.py" in failing.stdout
        (tmp_path / "f.py").unlink()
        assert run().returncode == 1


class TestCheckoutLineEndings:
    def _write(self, root: Path, header: bytes) -> Path:
        feature = root / "dataset" / "r_task" / "task1" / "feature1"
        feature.mkdir(parents=True)
        (feature / "feature.patch").write_bytes(header + b"--- a/x\n+++ b/x\n")
        return root / "dataset"

    def test_an_lf_checkout_passes(self, tmp_path: Path) -> None:
        check_checkout_line_endings(self._write(tmp_path, b"diff --git a/x b/x\n"))

    def test_a_crlf_checkout_is_refused_with_the_fix_named(self, tmp_path: Path) -> None:
        with pytest.raises(CooperBenchImportError, match="core.autocrlf=false"):
            check_checkout_line_endings(self._write(tmp_path, b"diff --git a/x b/x\r\n"))


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "user.name=t",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=cwd,
        capture_output=True,
        check=True,
    )
    return completed.stdout.decode("utf-8")


class TestGitBaseResolver:
    """Against a throwaway local repository: no network, real git."""

    @pytest.fixture
    def upstream(self, tmp_path: Path) -> tuple[Path, str]:
        repo = tmp_path / "upstream"
        repo.mkdir()
        _git(repo, "init", "-q")
        (repo / "src").mkdir()
        (repo / "src" / "a.py").write_bytes(b"one\r\ntwo\r\n")
        (repo / "blob.bin").write_bytes(b"\x00\x01\x02")
        (repo / "latin.txt").write_bytes(b"caf\xe9\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "base")
        return repo, _git(repo, "rev-parse", "HEAD").strip()

    def test_reads_text_exactly_and_maps_absent_and_binary(
        self, tmp_path: Path, upstream: tuple[Path, str]
    ) -> None:
        repo, commit = upstream
        resolver = GitBaseResolver(tmp_path / "cache")
        try:
            files = resolver.read_files(
                BaseSpec(str(repo), commit),
                ["src/a.py", "absent.py", "blob.bin", "latin.txt"],
            )
        except BaseResolutionError as exc:
            pytest.skip(f"this git cannot fetch a commit from a local path: {exc}")
        assert files["src/a.py"] == "one\r\ntwo\r\n"
        assert files["absent.py"] is None
        assert files["blob.bin"] is BINARY
        assert files["latin.txt"] is BINARY

    def test_an_unknown_commit_is_a_resolution_error_not_a_crash(
        self, tmp_path: Path, upstream: tuple[Path, str]
    ) -> None:
        repo, _ = upstream
        resolver = GitBaseResolver(tmp_path / "cache")
        with pytest.raises(BaseResolutionError):
            resolver.read_files(BaseSpec(str(repo), "b" * 40), ["src/a.py"])


class TestSummarize:
    def _record(self, status: str, reason: str | None = None, **extra) -> dict:
        return {
            "pair_id": f"{status}/{reason}/{len(extra)}/{id(extra)}",
            "repo": "r",
            "task": "t",
            "status": status,
            "reason": reason,
            **extra,
        }

    def test_counts_and_reasons(self) -> None:
        results = {
            str(i): record
            for i, record in enumerate(
                [
                    self._record("not_sensitive", contested_paths=["p"]),
                    self._record("sensitive", contested_paths=["p"]),
                    self._record("skipped", "no_coordination_dependency: disjoint"),
                    self._record("failed", "patch_does_not_apply: boom"),
                    self._record("failed", "patch_does_not_apply: bang"),
                ]
            )
        }
        summary = summarize(results)
        assert summary["pairs_total"] == 5
        assert (summary["sensitive"], summary["not_sensitive"]) == (1, 1)
        assert (summary["skipped"], summary["failed"], summary["gated"]) == (1, 2, 2)
        assert summary["reasons"]["failed: patch_does_not_apply"] == 2
        assert summary["reasons"]["skipped: no_coordination_dependency"] == 1
        assert summary["pairs_with_contested_paths"] == 2

    def test_an_empty_batch_reports_zero_pairs_not_a_crash(self) -> None:
        assert summarize({})["pairs_total"] == 0
