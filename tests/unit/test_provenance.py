"""Provenance: environment capture and artifact manifests (§30–§33).

The manifest tests mutate, delete and add files — always in `tmp_path`,
never in `data/raw/`. §31 makes raw data immutable, and a test that edited
it to prove tampering is detectable would be doing the thing it is checking
against.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from causalmesh.provenance import (
    Environment,
    GitState,
    Manifest,
    ManifestError,
    build,
    check,
    freeze_hash,
    hash_file,
)

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]


def make_collection(root: Path, *, runs: int = 3) -> Path:
    directory = root / "exp"
    for index in range(runs):
        run_dir = directory / f"exp__task__C{index}__r0000"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(
            json.dumps({"arm": f"C{index}", "result": {"run_id": f"r{index}"}}),
            encoding="utf-8",
        )
    return directory


class TestFreezeHash:
    def test_key_order_does_not_change_the_hash(self) -> None:
        """A freeze hash that depended on dict ordering would report a
        configuration change that never happened."""
        assert freeze_hash({"a": 1, "b": 2}) == freeze_hash({"b": 2, "a": 1})

    def test_a_different_value_changes_the_hash(self) -> None:
        assert freeze_hash({"window": 8}) != freeze_hash({"window": 9})

    def test_it_is_stable_across_calls(self) -> None:
        config = {"arms": ["C0", "C1"], "repetitions": 3}
        assert freeze_hash(config) == freeze_hash(config)


class TestGitState:
    def test_a_real_checkout_reports_a_commit(self) -> None:
        state = GitState.capture(REPO)
        assert state.commit != "unknown"
        assert len(state.commit) == 40

    def test_a_non_repository_is_unknown_rather_than_an_error(self, tmp_path: Path) -> None:
        """A directory that is not a repository is a normal condition: the
        answer is "unattributable", not a crash."""
        state = GitState.capture(tmp_path)
        assert state.commit == "unknown"
        assert state.attributable is False

    def test_a_dirty_tree_is_not_attributable(self) -> None:
        """A commit hash alone implies the tree matched it.

        A result produced from uncommitted changes cannot be reproduced
        from the hash it names, so `attributable` requires both.
        """
        assert GitState(commit="a" * 40, dirty=True).attributable is False
        assert GitState(commit="a" * 40, dirty=False).attributable is True
        # dirty=None means git answered but the status call failed, which
        # is not the same fact as a clean tree.
        assert GitState(commit="a" * 40, dirty=None).attributable is False


class TestEnvironment:
    def test_capture_records_the_interpreter_and_machine(self) -> None:
        env = Environment.capture(REPO)
        assert env.python_version.count(".") == 2
        assert env.platform_name
        assert env.machine_id

    def test_the_run_config_subset_is_what_runs_carry(self) -> None:
        """These three `RunConfig` fields existed and defaulted to
        "unknown" because nothing populated them."""
        subset = Environment.capture(REPO).to_run_config()
        assert set(subset) == {"git_commit", "machine_id", "operator_id"}


class TestManifestBuild:
    def test_every_artifact_is_hashed(self, tmp_path: Path) -> None:
        directory = make_collection(tmp_path)
        manifest = build(directory, repository_root=REPO)
        assert len(manifest.artifacts) == 3
        assert all(len(entry.sha256) == 64 for entry in manifest.artifacts)
        assert manifest.total_bytes > 0

    def test_the_mutable_index_is_excluded(self, tmp_path: Path) -> None:
        """index.db records progress, not evidence.

        Hashing it would make every manifest disagree with the next run's
        copy of the same collection.
        """
        directory = make_collection(tmp_path)
        (directory / "index.db").write_bytes(b"sqlite")
        manifest = build(directory, repository_root=REPO)
        assert not any(entry.path == "index.db" for entry in manifest.artifacts)

    def test_an_empty_collection_is_refused(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        with pytest.raises(ManifestError):
            build(empty, repository_root=REPO)

    def test_a_missing_directory_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestError):
            build(tmp_path / "nope", repository_root=REPO)

    def test_it_round_trips_through_disk(self, tmp_path: Path) -> None:
        directory = make_collection(tmp_path)
        manifest = build(
            directory,
            repository_root=REPO,
            now=datetime(2026, 9, 15, tzinfo=UTC),
        )
        path = manifest.write(tmp_path / "m.json")
        reloaded = Manifest.read(path)
        assert reloaded.to_dict() == manifest.to_dict()

    def test_a_malformed_manifest_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"experiment_id": "x"}), encoding="utf-8")
        with pytest.raises(ManifestError):
            Manifest.read(path)


class TestManifestCheck:
    """The mutation battery: a checker that cannot fail proves nothing."""

    def test_an_untouched_collection_is_intact(self, tmp_path: Path) -> None:
        directory = make_collection(tmp_path)
        manifest = build(directory, repository_root=REPO)
        assert check(manifest, directory).intact

    def test_a_changed_artifact_is_detected(self, tmp_path: Path) -> None:
        directory = make_collection(tmp_path)
        manifest = build(directory, repository_root=REPO)

        target = next(directory.rglob("run.json"))
        target.write_text(json.dumps({"tampered": True}), encoding="utf-8")

        result = check(manifest, directory)
        assert not result.intact
        assert len(result.changed) == 1
        assert not result.missing

    def test_a_deleted_artifact_is_detected(self, tmp_path: Path) -> None:
        directory = make_collection(tmp_path)
        manifest = build(directory, repository_root=REPO)

        next(directory.rglob("run.json")).unlink()

        result = check(manifest, directory)
        assert not result.intact
        assert len(result.missing) == 1

    def test_an_added_file_is_reported_without_breaking_integrity(self, tmp_path: Path) -> None:
        """An added file was never claimed by the manifest.

        Its presence says nothing about the evidence the manifest does
        cover — most often it is simply a later run in the same directory.
        """
        directory = make_collection(tmp_path)
        manifest = build(directory, repository_root=REPO)

        (directory / "notes.txt").write_text("hello", encoding="utf-8")

        result = check(manifest, directory)
        assert result.added == ("notes.txt",)
        assert result.intact

    def test_a_one_byte_change_is_enough(self, tmp_path: Path) -> None:
        directory = make_collection(tmp_path)
        manifest = build(directory, repository_root=REPO)

        target = next(directory.rglob("run.json"))
        content = target.read_text(encoding="utf-8")
        target.write_text(content + " ", encoding="utf-8")

        assert not check(manifest, directory).intact


class TestHashFile:
    def test_identical_content_hashes_identically(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        a.write_bytes(b"same")
        b.write_bytes(b"same")
        assert hash_file(a) == hash_file(b)

    def test_a_large_file_is_read_in_blocks(self, tmp_path: Path) -> None:
        """Run artifacts carry whole chains and can be large."""
        big = tmp_path / "big"
        big.write_bytes(b"x" * (3 << 20))
        assert len(hash_file(big)) == 64
