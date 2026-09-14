"""A live view of a collection while it executes.

The monitor is a **reader**. It opens the run index and the artifacts a
collection is producing and renders them; it never advances a run, claims
one, or writes anything. That separation is what makes it safe to attach to
a collection already in flight — and it is only possible because progress
lives in the index rather than in the executing process, which is the same
property that makes `experiment run` resumable.

Built on `rich.Live` rather than Textual: rich is already a dependency, and
a monitor that added a second UI framework to run would be a heavier ask
than the feature is worth.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Arm colours are fixed here so the same arm reads the same everywhere in
# the interface. They match the palette the landing page uses.
ARM_STYLE = {"C0": "dark_orange3", "C1": "grey62", "C2": "green3", "C3": "yellow3"}

STATE_STYLE = {
    "COMPLETED": "green3",
    "RUNNING": "cyan",
    "PLANNED": "grey50",
    "FAILED": "red3",
    "TIMED_OUT": "red3",
    "ABANDONED": "yellow3",
}


@dataclass
class RunView:
    """One run, as the monitor currently understands it."""

    run_id: str
    arm: str
    task_id: str
    state: str
    coordination_bytes: int = 0
    denials: int = 0
    events: int = 0
    succeeded: bool | None = None
    reproducible: bool = True

    @property
    def short_id(self) -> str:
        """The repetition suffix; the rest is the same for every row."""
        return self.run_id.rsplit("__", 1)[-1] if "__" in self.run_id else self.run_id

    @property
    def outcome(self) -> str:
        if self.state in {"PLANNED", "RUNNING"}:
            return "-"
        if self.succeeded is None:
            return "unknown"
        return "passed" if self.succeeded else "failed"


@dataclass
class Snapshot:
    """Everything the monitor knows at one instant."""

    experiment_id: str
    runs: list[RunView] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    started_at: float = field(default_factory=time.monotonic)
    connectors: list[dict[str, Any]] = field(default_factory=list)
    reproducible: bool = True

    @property
    def total(self) -> int:
        return len(self.runs)

    @property
    def finished(self) -> int:
        return sum(1 for run in self.runs if run.state not in {"PLANNED", "RUNNING"})

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def total_bytes(self) -> int:
        return sum(run.coordination_bytes for run in self.runs)

    @property
    def total_denials(self) -> int:
        return sum(run.denials for run in self.runs)

    def by_arm(self) -> dict[str, list[RunView]]:
        grouped: dict[str, list[RunView]] = {}
        for run in self.runs:
            grouped.setdefault(run.arm, []).append(run)
        return dict(sorted(grouped.items()))


def read_snapshot(experiment_dir: Path, *, started_at: float | None = None) -> Snapshot:
    """Build a snapshot from what is on disk right now.

    Artifacts are read where they exist and the index supplies the rest, so
    a run that has finished shows its real cost while one still executing
    shows its state. Reading only the index would leave every row blank
    until the collection ended; reading only artifacts would not show a run
    until it was over.
    """
    experiment_dir = Path(experiment_dir)
    snapshot = Snapshot(
        experiment_id=experiment_dir.name,
        started_at=started_at if started_at is not None else time.monotonic(),
    )

    index_path = experiment_dir / "index.db"
    records: dict[str, dict[str, Any]] = {}
    if index_path.is_file():
        records = _read_index(index_path, experiment_dir.name)

    for run_id, record in sorted(records.items()):
        view = RunView(
            arm=record.get("arm", "?"),
            run_id=run_id,
            state=str(record.get("state", "PLANNED")).upper(),
            task_id=record.get("task_id", "?"),
        )
        _merge_artifact(experiment_dir / run_id, view)
        snapshot.runs.append(view)

    # A collection that has produced artifacts without an index still shows:
    # an export copied from another machine has no index at all.
    if not records:
        for run_dir in sorted(p for p in experiment_dir.iterdir() if p.is_dir()):
            if not (run_dir / "run.json").is_file():
                continue
            view = RunView(arm="?", run_id=run_dir.name, state="COMPLETED", task_id="?")
            _merge_artifact(run_dir, view)
            snapshot.runs.append(view)

    for run in snapshot.runs:
        snapshot.counts[run.state] = snapshot.counts.get(run.state, 0) + 1
    # One nondeterministic run is enough to make the collection
    # non-reproducible; the warning is about the whole set.
    snapshot.reproducible = all(run.reproducible for run in snapshot.runs)
    return snapshot


def _read_index(index_path: Path, experiment_id: str) -> dict[str, dict[str, Any]]:
    """Read run rows without taking a write lock.

    Opened read-only through a URI so attaching a monitor can never block
    the process doing the actual work.
    """
    import sqlite3

    try:
        connection = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, timeout=2.0)
    except sqlite3.Error:
        return {}
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT run_id, arm, task_id, state FROM runs WHERE experiment_id = ?",
            (experiment_id,),
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
    return {row["run_id"]: dict(row) for row in rows}


def _merge_artifact(run_dir: Path, view: RunView) -> None:
    """Fold a finished run's recorded costs into its row."""
    artifact_path = run_dir / "run.json"
    if not artifact_path.is_file():
        return
    try:
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A partially written artifact is normal while a run is finishing.
        return
    result = artifact.get("result") or {}
    outcome = result.get("outcome")
    # Absent means an older artifact written before the field existed, which
    # was MockAgent-driven and therefore reproducible. Only an explicit
    # false demotes the collection.
    view.reproducible = artifact.get("reproducible", True) is not False
    view.arm = artifact.get("arm") or view.arm
    view.coordination_bytes = int(result.get("coordination_bytes") or 0)
    view.denials = len(result.get("denials") or ())
    view.events = int(result.get("events") or 0)
    view.succeeded = outcome.get("succeeded") if isinstance(outcome, dict) else None
    view.task_id = result.get("task_id") or view.task_id


# -- rendering -------------------------------------------------------------


def _header(snapshot: Snapshot) -> RenderableType:
    done, total = snapshot.finished, snapshot.total
    bar_width = 28
    filled = int(bar_width * done / total) if total else 0
    bar = Text("=" * filled + "." * (bar_width - filled), style="green3")

    line = Text()
    line.append(f"{snapshot.experiment_id}  ", style="bold")
    line.append("[")
    line.append_text(bar)
    line.append(f"] {done}/{total}  ")
    line.append(f"{snapshot.elapsed_s:.0f}s", style="grey62")
    if not snapshot.reproducible:
        line.append("   NOT REPRODUCIBLE", style="bold dark_orange3")
    return line


def _runs_table(snapshot: Snapshot) -> Table:
    table = Table(box=None, pad_edge=False, header_style="bold grey62")
    for column in ("arm", "task", "run", "state", "outcome", "bytes", "denials"):
        table.add_column(column)

    for arm, runs in snapshot.by_arm().items():
        style = ARM_STYLE.get(arm, "white")
        for index, run in enumerate(runs):
            outcome_style = {
                "passed": "green3",
                "failed": "red3",
                "unknown": "yellow3",
            }.get(run.outcome, "grey50")
            table.add_row(
                Text(arm if index == 0 else "", style=f"bold {style}"),
                Text(run.task_id[:26], style="grey70"),
                Text(run.short_id, style="grey62"),
                Text(run.state, style=STATE_STYLE.get(run.state, "white")),
                Text(run.outcome, style=outcome_style),
                Text(str(run.coordination_bytes) if run.coordination_bytes else "-"),
                Text(str(run.denials) if run.denials else "-", style="yellow3"),
            )
    return table


def _footer(snapshot: Snapshot) -> RenderableType:
    line = Text()
    line.append("coordination ", style="grey62")
    line.append(f"{snapshot.total_bytes} B", style="bold")
    line.append("   denials ", style="grey62")
    line.append(str(snapshot.total_denials), style="bold yellow3")
    for state in ("COMPLETED", "FAILED", "RUNNING", "PLANNED"):
        if snapshot.counts.get(state):
            line.append(f"   {state.lower()} ", style="grey62")
            line.append(str(snapshot.counts[state]), style=STATE_STYLE.get(state, "white"))

    if snapshot.connectors:
        line.append("\n")
        line.append("agents ", style="grey62")
        for connector in snapshot.connectors:
            usable = connector.get("usable")
            line.append(
                f"{connector['name']} ", style="green3" if usable else "grey50"
            )
    return line


def render(snapshot: Snapshot) -> RenderableType:
    """The whole frame."""
    return Panel(
        Group(_header(snapshot), Text(), _runs_table(snapshot), Text(), _footer(snapshot)),
        border_style="grey35",
        title="causalmesh",
        title_align="left",
    )
