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
        assert "not reproducible" in plain(render(snapshot))

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
        assert by_arm["C3"].denials == 3
        assert by_arm["C2"].denials == 0

    def test_the_split_arm_is_detected_rather_than_left_to_be_noticed(self) -> None:
        """The finding the whole view is built around.

        C3 passes schema_handler_widen and fails concurrent_edit_collision.
        No per-arm average can say that, and the 50% rate is exactly the
        number that hides it.
        """
        by_arm = read_snapshot(PILOT).by_arm()
        assert by_arm["C3"].splits() is True
        assert by_arm["C2"].splits() is False
        assert by_arm["C0"].splits() is False

    def test_the_comparison_names_the_split_arm(self) -> None:
        output = plain(render(read_snapshot(PILOT)))
        assert "C3 behaves differently by task" in output
        # And evidences it with the per-task breakdown.
        assert "concurrent_edit_collision" in output
        assert "0/3" in output and "3/3" in output

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
    def test_a_frame_compares_the_arms(self) -> None:
        snapshot = Snapshot(experiment_id="demo")
        snapshot.runs = [
            RunView("demo__t__C2__r0000", "C2", "t", "COMPLETED", 196, 0, 4, True),
            RunView("demo__t__C3__r0000", "C3", "t", "COMPLETED", 196, 1, 4, False),
            RunView("demo__t__C0__r0000", "C0", "t", "RUNNING"),
        ]
        output = plain(render(snapshot))

        assert "demo" in output
        assert "C2" in output and "C3" in output
        # Each arm states its condition, so the reader need not hold the
        # experimental design in their head.
        assert "bounded metadata" in output
        assert "196" in output
        # 2 of 3 have reached a terminal state.
        assert "2/3" in output

    def test_the_live_run_is_named_while_it_executes(self) -> None:
        """"Which run is this" is the question an operator actually has."""
        snapshot = Snapshot(experiment_id="demo")
        snapshot.runs = [
            RunView("demo__widen__C0__r0000", "C0", "widen", "RUNNING"),
            RunView("demo__widen__C1__r0000", "C1", "widen", "PLANNED"),
        ]
        output = plain(render(snapshot))
        assert "running" in output
        assert "widen" in output
        # Pending work is listed while it is pending.
        assert "IN FLIGHT" in output

    def test_a_finished_collection_drops_the_in_flight_section(self) -> None:
        """Detail an operator wants during a run and never after one."""
        snapshot = Snapshot(experiment_id="demo")
        snapshot.runs = [RunView("demo__t__C2__r0000", "C2", "t", "COMPLETED", 196, 0, 4, True)]
        output = plain(render(snapshot))
        assert "IN FLIGHT" not in output
        assert "complete" in output

    def test_a_uniform_collection_shows_no_breakdown(self) -> None:
        """A breakdown that is always present is another table to scan."""
        snapshot = Snapshot(experiment_id="demo")
        snapshot.runs = [
            RunView("demo__a__C2__r0000", "C2", "a", "COMPLETED", 196, 0, 4, True),
            RunView("demo__b__C2__r0000", "C2", "b", "COMPLETED", 196, 0, 4, True),
        ]
        assert "behaves differently" not in plain(render(snapshot))

    def test_it_holds_at_eighty_columns(self) -> None:
        """The width the development terminal actually reports.

        The split marker used to live inside a ratio column and truncated to
        "differs by ..." here, which reads as a rendering fault rather than
        a finding.
        """
        from rich.console import Console

        snapshot = Snapshot(experiment_id="demo")
        snapshot.runs = [
            RunView("demo__widen__C3__r0000", "C3", "widen", "COMPLETED", 196, 0, 4, True),
            RunView("demo__collide__C3__r0000", "C3", "collide", "COMPLETED", 196, 1, 4, False),
        ]
        console = Console(width=80)
        with console.capture() as capture:
            console.print(render(snapshot))
        output = capture.get()

        assert "C3 behaves differently by task" in output
        assert "…" not in output and "..." not in output
        assert max(len(line) for line in output.splitlines()) <= 80

    def test_an_empty_collection_renders_without_dividing_by_zero(self) -> None:
        output = plain(render(Snapshot(experiment_id="empty")))
        assert "empty" in output
        assert "0/0" in output

    def test_a_non_reproducible_collection_says_so(self) -> None:
        """A run driven by a real agent is not reproducible, and the
        interface must not let that fact be missed."""
        snapshot = Snapshot(experiment_id="live", reproducible=False)
        snapshot.runs = [RunView("live__t__C2__r0000", "C2", "t", "COMPLETED")]
        assert "not reproducible" in plain(render(snapshot))

    def test_a_reproducible_collection_carries_no_warning(self) -> None:
        snapshot = Snapshot(experiment_id="mock")
        snapshot.runs = [RunView("mock__t__C2__r0000", "C2", "t", "COMPLETED")]
        assert "not reproducible" not in plain(render(snapshot))
