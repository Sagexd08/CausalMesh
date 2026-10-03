"""End-to-end test of the CooperBench batch importer on a SYNTHETIC dataset (backlog section 54).

A small dataset is built in a temp directory with real `git diff` output
and a fake base-repo resolver, so the test is offline and does not depend on
the real CooperBench data. It pins the batch machinery (pairing, error
isolation, resume, the results file), not any fact about the real dataset.

The gate verdicts asserted here are the platform's honest ones: a pair whose
features share a path is NOT SENSITIVE because the contested-path merge is
winner-take-all, and a pair whose features share nothing is skipped by the
structural gate rather than given a verdict.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from causalmesh.tasks.cooperbench import CooperBenchImportError
from causalmesh.tasks.cooperbench_batch import (
    BaseFile,
    BaseResolutionError,
    BaseSpec,
    BatchOptions,
    run_batch,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "tests" / "fixtures" / "cooperbench_sample"
SHA_ALPHA = "1" * 40
SHA_ALPHA_2 = "2" * 40
SHA_TINY = "3" * 40

ALPHA_A = "".join(f"a_line{n}\n" for n in range(1, 31))
ALPHA_B = "b_one\nb_two\n"

BOGUS_PATCH = (
    "diff --git a/a.py b/a.py\n"
    "--- a/a.py\n"
    "+++ b/a.py\n"
    "@@ -1,3 +1,3 @@\n"
    " context that is not in the file\n"
    "-neither is this\n"
    "+replacement\n"
)


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


def _write_task(
    dataset: Path,
    repo: str,
    task: str,
    base: dict[str, str],
    features: dict[int, dict[str, str] | str],
    *,
    sha: str | None,
    scratch: Path,
) -> None:
    """One task on disk: real `git diff` patches, or a literal patch string."""
    work = scratch / f"{repo}_{task}"
    work.mkdir(parents=True)
    _git(work, "init", "-q")
    for path, content in base.items():
        (work / path).write_bytes(content.encode("utf-8"))
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "base")

    task_dir = dataset / repo / task
    for number, change in features.items():
        feature = task_dir / f"feature{number}"
        feature.mkdir(parents=True)
        (feature / "feature.md").write_text(f"# Feature {number}\n\nDo thing {number}.\n")
        if isinstance(change, str):
            patch = change
        else:
            for path, content in change.items():
                (work / path).write_bytes(content.encode("utf-8"))
            _git(work, "add", "-A")
            patch = _git(work, "diff", "--cached")
            _git(work, "reset", "-q", "--hard")
        (feature / "feature.patch").write_bytes(patch.encode("utf-8"))
    if sha is not None:
        (task_dir / "Dockerfile").write_text(
            f"FROM x\nRUN git clone https://example.invalid/{repo}.git repo && \\\n"
            f"    cd repo && \\\n    git checkout {sha}\n"
        )


class FakeResolver:
    """Serves base files from memory and records what it was asked for."""

    def __init__(self, trees: dict[str, dict[str, str]], failing: frozenset[str] = frozenset()):
        self.trees = trees
        self.failing = failing
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def read_files(self, spec: BaseSpec, paths) -> dict[str, BaseFile]:
        wanted = tuple(sorted(set(paths)))
        self.calls.append((spec.commit, wanted))
        if spec.commit in self.failing:
            raise BaseResolutionError("simulated fetch failure")
        tree = self.trees[spec.commit]
        return {path: tree.get(path) for path in wanted}


def _tiny_base() -> dict[str, str]:
    base = SAMPLE / "base_repo"
    return {
        path.relative_to(base).as_posix(): path.read_text(encoding="utf-8")
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


@pytest.fixture(scope="module")
def dataset(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("cb_batch_dataset")
    ds = root / "dataset"
    scratch = root / "scratch"
    base = {"a.py": ALPHA_A, "b.py": ALPHA_B}
    lines = ALPHA_A.splitlines(keepends=True)
    top = "".join(["a_TOP_CHANGED\n", *lines[1:]])
    bottom = "".join([*lines[:-2], "a_BOTTOM_CHANGED\n", lines[-1]])
    _write_task(
        ds,
        "alpha_task",
        "task1",
        base,
        {
            1: {"a.py": top},
            2: {"a.py": bottom},
            3: {"b.py": ALPHA_B + "b_three\n"},
            4: BOGUS_PATCH,
        },
        sha=SHA_ALPHA,
        scratch=scratch,
    )
    _write_task(
        ds,
        "alpha_task",
        "task2",
        base,
        {1: {"b.py": ALPHA_B + "x\n"}, 2: {"b.py": "y\n" + ALPHA_B}},
        sha=None,  # no Dockerfile and no setup.sh: the base cannot be named
        scratch=scratch,
    )
    # The hand-built sample: features 1 and 2 both edit src/greeter.py.
    shutil.copytree(SAMPLE / "dataset" / "tinyrepo", ds / "tinyrepo")
    (ds / "tinyrepo" / "task1" / "Dockerfile").write_text(
        f"RUN git clone https://example.invalid/tiny.git repo && cd repo && git checkout {SHA_TINY}\n"
    )
    return ds


@pytest.fixture(scope="module")
def trees() -> dict[str, dict[str, str]]:
    base = {"a.py": ALPHA_A, "b.py": ALPHA_B}
    return {SHA_ALPHA: base, SHA_ALPHA_2: base, SHA_TINY: _tiny_base()}


@pytest.fixture(scope="module")
def first_run(dataset: Path, trees, tmp_path_factory):
    out = tmp_path_factory.mktemp("cb_batch_out")
    resolver = FakeResolver(trees)
    document = run_batch(BatchOptions(dataset_dir=dataset, output_dir=out), resolver=resolver)
    return out, document, resolver


def _by_pair(document: dict) -> dict[str, dict]:
    return {record["pair_id"]: record for record in document["pairs"]}


class TestTheBatch:
    def test_every_pair_gets_exactly_one_terminal_record(self, first_run) -> None:
        _, document, _ = first_run
        # alpha/task1: C(4,2)=6, alpha/task2: 1, tinyrepo/task1: 1
        assert document["summary"]["pairs_total"] == 8
        assert len(document["pairs"]) == 8
        assert set(document["summary"]["status"]) <= {
            "sensitive",
            "not_sensitive",
            "skipped",
            "failed",
        }

    def test_a_shared_path_pair_is_gated_and_reported_not_sensitive(self, first_run) -> None:
        _, document, _ = first_run
        record = _by_pair(document)["alpha_task/task1/f1-f2"]
        assert record["status"] == "not_sensitive"
        assert record["contested_paths"] == ["a.py"]
        assert record["sensitivity"]["isolated_successes"] == 0
        assert record["sensitivity"]["informed_successes"] == 0
        assert "indistinguishable" in record["sensitivity"]["detail"]
        # The two edits are far apart, so git can merge them: the oracle's
        # expectation equals git's own merge, and the failure above is the
        # platform's winner-take-all merge, not an unsatisfiable oracle.
        assert record["oracle"]["sequential_apply"] == "matches"

    def test_the_hand_built_sample_reproduces_the_documented_verdict(self, first_run) -> None:
        _, document, _ = first_run
        record = _by_pair(document)["tinyrepo/task1/f1-f2"]
        assert record["status"] == "not_sensitive"
        assert record["contested_paths"] == ["src/greeter.py"]
        assert record["oracle"]["sequential_apply"] == "not_applicable"

    def test_a_disjoint_pair_is_skipped_by_the_structural_gate_with_its_reason(
        self, first_run
    ) -> None:
        _, document, _ = first_run
        record = _by_pair(document)["alpha_task/task1/f1-f3"]
        assert record["status"] == "skipped"
        assert record["reason"].startswith("no_coordination_dependency")
        assert "sensitivity" not in record

    def test_a_patch_that_does_not_apply_fails_only_its_own_pairs(self, first_run) -> None:
        _, document, _ = first_run
        pairs = _by_pair(document)
        for pair_id in (
            "alpha_task/task1/f1-f4",
            "alpha_task/task1/f2-f4",
            "alpha_task/task1/f3-f4",
        ):
            assert pairs[pair_id]["status"] == "failed", pair_id
            assert pairs[pair_id]["reason"].startswith("patch_does_not_apply")
            assert pairs[pair_id]["stage"] == "import"
        assert pairs["alpha_task/task1/f1-f2"]["status"] == "not_sensitive"

    def test_an_unresolvable_base_fails_that_task_and_the_batch_continues(self, first_run) -> None:
        _, document, _ = first_run
        pairs = _by_pair(document)
        record = pairs["alpha_task/task2/f1-f2"]
        assert record["status"] == "failed"
        assert record["stage"] == "base"
        assert record["reason"].startswith("base_unavailable")
        assert pairs["tinyrepo/task1/f1-f2"]["status"] == "not_sensitive"

    def test_summary_counts_add_up_and_carry_reasons(self, first_run) -> None:
        _, document, _ = first_run
        summary = document["summary"]
        assert summary["not_sensitive"] == 2
        assert summary["sensitive"] == 0
        assert summary["gated"] == 2
        assert summary["skipped"] == 2  # f1-f3 and f2-f3 of alpha/task1
        assert summary["failed"] == 4  # three patch failures and one base failure
        assert sum(summary["status"].values()) == summary["pairs_total"]
        assert summary["reasons"]["failed: patch_does_not_apply"] == 3
        assert summary["reasons"]["failed: base_unavailable"] == 1
        assert summary["reasons"]["skipped: no_coordination_dependency"] == 2

    def test_the_results_files_are_machine_readable_and_state_their_provenance(
        self, first_run
    ) -> None:
        out, document, _ = first_run
        on_disk = json.loads((out / "results.json").read_text(encoding="utf-8"))
        assert on_disk["summary"] == document["summary"]
        # Outside a git checkout the dataset commit is unknown, never a blank or zero.
        assert on_disk["envelope"]["dataset_commit"] == "unknown"
        assert on_disk["envelope"]["dataset_license_declared"] == "unknown"
        assert "mock agent" in on_disk["envelope"]["note"]
        lines = (out / "results.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 8
        assert all(json.loads(line)["pair_id"] for line in lines)

    def test_imported_tasks_and_fixtures_are_written_where_promised(self, first_run) -> None:
        out, _, _ = first_run
        assert (out / "tasks" / "cb_alpha_task1_f1_f2.yaml").is_file()
        fixture = out / "fixtures" / "cb_alpha_task1_f1_f2"
        assert (fixture / "a.py").is_file()
        assert (fixture / "cb_verify.py").is_file() and (fixture / "cb_expected.json").is_file()
        assert (fixture / "run_tests.sh").is_file()
        # The dataset's own run_tests.sh (network, toolchains) is never installed.
        tiny = out / "fixtures" / "cb_tinyrepo_task1_f1_f2"
        assert "cb_verify.py" in (tiny / "run_tests.sh").read_text(encoding="utf-8")
        assert not (tiny / "setup.sh").exists()

    def test_the_oracle_passes_the_merged_tree_and_fails_either_half(
        self, first_run, tmp_path: Path
    ) -> None:
        out, _, _ = first_run
        fixture = tmp_path / "fx"
        shutil.copytree(out / "fixtures" / "cb_alpha_task1_f1_f2", fixture)
        lines = ALPHA_A.splitlines(keepends=True)
        merged = "".join(["a_TOP_CHANGED\n", *lines[1:-2], "a_BOTTOM_CHANGED\n", lines[-1]])

        def verify() -> int:
            return subprocess.run(
                [sys.executable, "cb_verify.py"], cwd=fixture, capture_output=True, check=False
            ).returncode

        (fixture / "a.py").write_bytes(merged.encode("utf-8"))
        assert verify() == 0
        (fixture / "a.py").write_bytes(ALPHA_A.replace("a_line1\n", "a_TOP_CHANGED\n").encode())
        assert verify() == 1
        (fixture / "a.py").write_bytes(ALPHA_A.encode("utf-8"))
        assert verify() == 1


class TestResume:
    def test_a_second_run_redoes_only_what_did_not_finish(
        self, dataset: Path, trees, first_run, tmp_path: Path
    ) -> None:
        first_out, first_document, _ = first_run
        out = tmp_path / "resumed"
        shutil.copytree(first_out, out)
        before = {p["pair_id"]: p for p in first_document["pairs"]}
        # alpha/task2 now resolves (a fixed Dockerfile); everything else is as before.
        (dataset / "alpha_task" / "task2" / "Dockerfile").write_text(
            f"RUN git clone https://example.invalid/alpha.git repo && cd repo && git checkout {SHA_ALPHA_2}\n"
        )
        try:
            resolver = FakeResolver(trees)
            document = run_batch(
                BatchOptions(dataset_dir=dataset, output_dir=out), resolver=resolver
            )
        finally:
            (dataset / "alpha_task" / "task2" / "Dockerfile").unlink()

        asked = {commit for commit, _ in resolver.calls}
        assert SHA_TINY not in asked, "a finished task must not be re-resolved"
        assert SHA_ALPHA in asked, "alpha/task1 still has failed pairs, which are retried"
        after = _by_pair(document)
        for pair_id in ("alpha_task/task1/f1-f2", "tinyrepo/task1/f1-f2", "alpha_task/task1/f1-f3"):
            assert after[pair_id] == before[pair_id], f"{pair_id} was redone"
        assert after["alpha_task/task2/f1-f2"]["stage"] != "base"
        assert document["summary"]["pairs_total"] == 8

    def test_force_redoes_finished_pairs_too(self, dataset: Path, trees, tmp_path: Path) -> None:
        out = tmp_path / "out"
        options = BatchOptions(
            dataset_dir=dataset, output_dir=out, only_repos=frozenset({"tinyrepo"})
        )
        run_batch(options, resolver=FakeResolver(trees))
        resolver = FakeResolver(trees)
        run_batch(options, resolver=resolver)
        assert resolver.calls == []
        forced = FakeResolver(trees)
        run_batch(
            BatchOptions(
                dataset_dir=dataset,
                output_dir=out,
                only_repos=frozenset({"tinyrepo"}),
                force=True,
            ),
            resolver=forced,
        )
        assert forced.calls, "force must re-resolve a finished task"

    def test_a_torn_last_line_from_an_interrupted_run_is_ignored(
        self, dataset: Path, trees, tmp_path: Path
    ) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "results.jsonl").write_text(
            '{"pair_id": "tinyrepo/task1/f1-f2", "sta', encoding="utf-8"
        )
        document = run_batch(
            BatchOptions(dataset_dir=dataset, output_dir=out, only_repos=frozenset({"tinyrepo"})),
            resolver=FakeResolver(trees),
        )
        assert _by_pair(document)["tinyrepo/task1/f1-f2"]["status"] == "not_sensitive"


class TestIsolation:
    def test_a_failing_fetch_does_not_touch_other_tasks(
        self, dataset: Path, trees, tmp_path: Path
    ) -> None:
        resolver = FakeResolver(trees, failing=frozenset({SHA_ALPHA}))
        document = run_batch(
            BatchOptions(dataset_dir=dataset, output_dir=tmp_path / "out"), resolver=resolver
        )
        pairs = _by_pair(document)
        alpha = [r for r in document["pairs"] if r["task_id"].startswith("cb_alpha_task1_")]
        assert alpha and all(r["status"] == "failed" and r["stage"] == "base" for r in alpha)
        assert pairs["tinyrepo/task1/f1-f2"]["status"] == "not_sensitive"

    def test_a_crlf_checkout_stops_the_batch_before_any_pair_runs(
        self, tmp_path: Path, trees
    ) -> None:
        ds = tmp_path / "dataset" / "r_task" / "task1"
        for number in (1, 2):
            feature = ds / f"feature{number}"
            feature.mkdir(parents=True)
            (feature / "feature.patch").write_bytes(b"diff --git a/x b/x\r\n--- a/x\r\n+++ b/x\r\n")
        resolver = FakeResolver(trees)
        with pytest.raises(CooperBenchImportError, match="core.autocrlf=false"):
            run_batch(
                BatchOptions(dataset_dir=tmp_path / "dataset", output_dir=tmp_path / "out"),
                resolver=resolver,
            )
        assert resolver.calls == []


class TestThreeWayMerge:
    """`contested_merge="three_way"`: the platform's merge stops being winner-take-all."""

    @pytest.fixture(scope="class")
    def three_way(self, dataset: Path, trees, tmp_path_factory) -> dict:
        out = tmp_path_factory.mktemp("cb_batch_out_three_way")
        return run_batch(
            BatchOptions(dataset_dir=dataset, output_dir=out, contested_merge="three_way"),
            resolver=FakeResolver(trees),
        )

    def test_edits_to_different_parts_of_one_file_are_solved_in_both_arms(
        self, three_way: dict
    ) -> None:
        record = _by_pair(three_way)["alpha_task/task1/f1-f2"]
        assert record["sensitivity"]["isolated_successes"] == 1
        assert record["sensitivity"]["informed_successes"] == 1

    def test_the_same_pair_is_lost_under_the_default(self, first_run) -> None:
        """The control: the identical dataset, one option away, is not solved."""
        _, document, _ = first_run
        record = _by_pair(document)["alpha_task/task1/f1-f2"]
        assert record["sensitivity"]["isolated_successes"] == 0

    def test_insertions_at_the_same_place_still_fail(self, three_way: dict) -> None:
        """tinyrepo's features add a key at the same spot: a real conflict."""
        record = _by_pair(three_way)["tinyrepo/task1/f1-f2"]
        assert record["sensitivity"]["isolated_successes"] == 0

    def test_the_arms_still_never_differ(self, three_way: dict) -> None:
        """Replay agents do not read the channel, so no merge can make the gate sensitive."""
        assert three_way["summary"]["sensitive"] == 0
        assert all(
            record["sensitivity"]["isolated_successes"]
            == record["sensitivity"]["informed_successes"]
            for record in three_way["pairs"]
            if "sensitivity" in record
        )

    def test_the_summary_counts_the_pairs_the_platform_solved(self, three_way: dict) -> None:
        assert three_way["summary"]["gated_with_isolated_success"] >= 1

    def test_the_document_says_which_merge_produced_it(self, three_way: dict, first_run) -> None:
        assert three_way["options"]["contested_merge"] == "three_way"
        assert "three-way" in three_way["envelope"]["note"]
        assert "winner-take-all" not in three_way["envelope"]["note"]
        _, default_document, _ = first_run
        assert "contested_merge" not in default_document["options"], "a default run keeps its shape"
        assert "winner-take-all" in default_document["envelope"]["note"]
