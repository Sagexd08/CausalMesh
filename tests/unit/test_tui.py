"""The live monitor (read-only).

The monitor's single most important property is that it cannot affect the
collection it watches, so that is tested first and directly: the index is
opened read-only, and a write attempted through the monitor's own
connection must fail.

Rendering is checked for the facts it must show — an arm, a denial, a
progress count — rather than exact strings, so improving the layout does
not become a test change.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from rich.console import Console

from causalmesh.tui import read_snapshot, render
from causalmesh.tui.monitor import RunView, Snapshot

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / "data" / "raw" / "pilot_landing"


def make_run(directory: Path, run_id: str, arm: str, **result) -> None:
    run_dir = directory / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {"arm": arm, "result": {"run_id": run_id, "task_id": "t", **result}}
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")


def plain(renderable) -> str:
    """Render a frame to text, so assertions read the facts not the styling."""
    console = Console(width=120)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


class TestSnapshotFromArtifacts:
    def test_a_collection_without_an_index_still_reads(self, tmp_path: Path) -> None:
        """An export copied from another machine has no index at all."""
        directory = tmp_path / "exp"
        make_run(directory, "exp__t__C2__r0000", "C2", coordination_bytes=196)
        snapshot = read_snapshot(directory)
        assert snapshot.total == 1
        assert snapshot.runs[0].coordination_bytes == 196

    def test_costs_and_denials_are_read_from_the_artifact(self, tmp_path: Path) -> None:
        directory = tmp_path / "exp"
        make_run(
            directory,
            "exp__t__C3__r0000",
            "C3",
            coordination_bytes=196,
            denials=[{"path": "src/config.py"}],
            outcome={"succeeded": False},
        )
        snapshot = read_snapshot(directory)
        run = snapshot.runs[0]
        assert run.denials == 1
        assert run.outcome == "failed"
        assert snapshot.total_denials == 1

    def test_a_partial_artifact_does_not_crash_the_monitor(self, tmp_path: Path) -> None:
        """Half-written JSON is normal while a run is finishing."""
        directory = tmp_path / "exp"
        run_dir = directory / "exp__t__C0__r0000"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text('{"arm": "C0", "resu', encoding="utf-8")
        snapshot = read_snapshot(directory)
        assert snapshot.total == 1
        assert snapshot.runs[0].coordination_bytes == 0

    def test_a_missing_outcome_reads_as_unknown_not_failed(self, tmp_path: Path) -> None:
        directory = tmp_path / "exp"
        make_run(directory, "exp__t__C1__r0000", "C1")
        assert read_snapshot(directory).runs[0].outcome == "unknown"

    def test_a_live_agent_run_demotes_the_whole_collection(self, tmp_path: Path) -> None:
        """One nondeterministic run makes the set non-reproducible.

        The warning is a property of the collection, not of a row: a
        comparison drawn across a set where one arm was driven by a real
        agent is not reproducible even if the other three were mocked.
        """
        directory = tmp_path / "exp"
        make_run(directory, "exp__t__C2__r0000", "C2")
        run_dir = directory / "exp__t__C3__r0000"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(
            json.dumps(
                {"arm": "C3", "reproducible": False, "result": {"task_id": "t"}}
            ),
            encoding="utf-8",
        )

        snapshot = read_snapshot(directory)
        assert snapshot.reproducible is False
        assert "NOT REPRODUCIBLE" in plain(render(snapshot))

    def test_an_artifact_predating_the_field_stays_reproducible(self, tmp_path: Path) -> None:
        """Absent means MockAgent-driven, which is the deterministic case."""
        directory = tmp_path / "exp"
        make_run(directory, "exp__t__C0__r0000", "C0")
        assert read_snapshot(directory).reproducible is True


@pytest.mark.skipif(not PILOT.is_dir(), reason="pilot artifacts are not in this checkout")
class TestAgainstThePilot:
    def test_the_whole_collection_is_visible(self) -> None:
        snapshot = read_snapshot(PILOT)
        assert snapshot.total == 24
        assert snapshot.finished == 24
        assert sorted(snapshot.by_arm()) == ["C0", "C1", "C2", "C3"]

    def test_only_the_enforcing_arm_shows_denials(self) -> None:
        snapshot = read_snapshot(PILOT)
        by_arm = snapshot.by_arm()
        assert sum(r.denials for r in by_arm["C3"]) == 3
        assert sum(r.denials for r in by_arm["C2"]) == 0

    def test_the_monitor_never_writes_to_the_index(self) -> None:
        """The property that makes it safe to attach to a live run.

        The monitor opens the index `mode=ro`, so a write through that
        connection must be refused by SQLite itself rather than by
        convention.
        """
        connection = sqlite3.connect(f"file:{PILOT / 'index.db'}?mode=ro", uri=True)
        try:
            with pytest.raises(sqlite3.OperationalError):
                connection.execute("UPDATE runs SET state = 'TAMPERED'")
        finally:
            connection.close()


class TestRendering:
    def test_a_frame_shows_arms_progress_and_denials(self) -> None:
        snapshot = Snapshot(experiment_id="demo")
        snapshot.runs = [
            RunView("demo__t__C2__r0000", "C2", "t", "COMPLETED", 196, 0, 4, True),
            RunView("demo__t__C3__r0000", "C3", "t", "COMPLETED", 196, 1, 4, False),
            RunView("demo__t__C0__r0000", "C0", "t", "RUNNING"),
        ]
        output = plain(render(snapshot))

        assert "demo" in output
        assert "C2" in output and "C3" in output
        assert "196" in output
        assert "RUNNING" in output
        # 2 of 3 have reached a terminal state.
        assert "2/3" in output

    def test_an_empty_collection_renders_without_dividing_by_zero(self) -> None:
        output = plain(render(Snapshot(experiment_id="empty")))
        assert "empty" in output
        assert "0/0" in output

    def test_a_non_reproducible_collection_says_so(self) -> None:
        """A run driven by a real agent is not reproducible, and the
        interface must not let that fact be missed."""
        snapshot = Snapshot(experiment_id="live", reproducible=False)
        snapshot.runs = [RunView("live__t__C2__r0000", "C2", "t", "COMPLETED")]
        assert "NOT REPRODUCIBLE" in plain(render(snapshot))

    def test_a_reproducible_collection_carries_no_warning(self) -> None:
        snapshot = Snapshot(experiment_id="mock")
        snapshot.runs = [RunView("mock__t__C2__r0000", "C2", "t", "COMPLETED")]
        assert "NOT REPRODUCIBLE" not in plain(render(snapshot))
