"""A live view of a collection while it executes.

The monitor is a **reader**. It opens the run index and the artifacts a
collection is producing and renders them; it never advances a run, claims
one, or writes anything. That separation is what makes it safe to attach to
a collection already in flight — and it is only possible because progress
lives in the index rather than in the executing process, which is the same
property that makes `experiment run` resumable.

**What the instrument is for.** An experiment with four arms is a
comparison, so the view is built as one: arms are rows, and each row states
what that arm bought and what it cost. An earlier version listed every run
as a flat log, which rendered the project's central finding — an arm
passing one task and failing another — in exactly the same weight as
everything else, twenty-four near-identical lines deep. Listing is not
comparing.

Two facts have to survive a glance: how far the collection has got, and
what the arms are doing differently. Everything else is detail that appears
when there is something to see and is absent when there is not.

Built on `rich` because it is already a dependency; a monitor that made a
second UI framework a runtime requirement would cost more than it is worth.
Box characters are never written by hand: the terminal this was built for
reports cp1252, where a box-drawing glyph raises `UnicodeEncodeError` on
write. Rich substitutes ASCII for its own boxes; a literal in this file
would not be substituted. The layout holds at 80 columns, which is what
that terminal actually reports, and uses more width when it is given.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from causalmesh.tui.palette import (
    DENIAL,
    LIVE,
    RESULT_FAIL as FAIL,
    RESULT_PASS as PASS,
    TEXT,
    TEXT_FAINT,
    TEXT_MUTED,
    arm_style,
    supports_unicode,
)

STATE_STYLE = {
    "COMPLETED": TEXT_MUTED,
    "RUNNING": LIVE,
    "PLANNED": TEXT_FAINT,
    "FAILED": FAIL,
    "TIMED_OUT": FAIL,
    "ABANDONED": DENIAL,
}

# What each arm is, in the words the experiment uses. Stated here so the
# operator does not have to hold the design in their head to read the
# comparison in front of them.
ARM_CONDITION = {
    "C0": "no peer information",
    "C1": "full transcripts",
    "C2": "bounded metadata",
    "C3": "metadata + claims",
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
    def active(self) -> bool:
        return self.state in {"PLANNED", "RUNNING"}

    @property
    def outcome(self) -> str:
        if self.active:
            return "-"
        if self.succeeded is None:
            return "unknown"
        return "passed" if self.succeeded else "failed"


@dataclass
class ArmView:
    """One arm's runs, aggregated into the comparison the design asks for."""

    arm: str
    runs: list[RunView] = field(default_factory=list)

    @property
    def finished(self) -> list[RunView]:
        return [run for run in self.runs if not run.active]

    @property
    def known(self) -> list[RunView]:
        """Finished runs that reported an outcome.

        A run that crashed before evaluating is not a failure, and counting
        it as one would inflate every failure rate by however many crashed.
        """
        return [run for run in self.finished if run.succeeded is not None]

    @property
    def passed(self) -> int:
        return sum(1 for run in self.known if run.succeeded)

    @property
    def denials(self) -> int:
        return sum(run.denials for run in self.runs)

    @property
    def mean_bytes(self) -> float | None:
        """Mean over finished runs only.

        Averaging in runs that have not spent yet would make an arm look
        cheaper the earlier in the collection you looked at it.
        """
        finished = self.finished
        if not finished:
            return None
        return sum(run.coordination_bytes for run in finished) / len(finished)

    def tasks(self) -> dict[str, list[RunView]]:
        grouped: dict[str, list[RunView]] = {}
        for run in self.runs:
            grouped.setdefault(run.task_id, []).append(run)
        return dict(sorted(grouped.items()))

    def splits(self) -> bool:
        """Whether this arm behaves differently on different tasks.

        This is the finding the experiment exists to surface, so the view
        detects it rather than leaving it to be noticed. An arm that passes
        one task and fails another is saying something no per-arm average
        can say — and the average is exactly what hides it.
        """
        outcomes = [
            {run.succeeded for run in runs if run.succeeded is not None}
            for runs in self.tasks().values()
        ]
        decided = [values for values in outcomes if values]
        return len(decided) > 1 and {True} in decided and {False} in decided


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
        return sum(1 for run in self.runs if not run.active)

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def total_bytes(self) -> int:
        return sum(run.coordination_bytes for run in self.runs)

    @property
    def total_denials(self) -> int:
        return sum(run.denials for run in self.runs)

    @property
    def complete(self) -> bool:
        return bool(self.total) and self.finished >= self.total

    def current(self) -> RunView | None:
        """The run executing right now, if any."""
        return next((run for run in self.runs if run.state == "RUNNING"), None)

    def by_arm(self) -> dict[str, ArmView]:
        grouped: dict[str, ArmView] = {}
        for run in self.runs:
            grouped.setdefault(run.arm, ArmView(arm=run.arm)).runs.append(run)
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
    if not records and experiment_dir.is_dir():
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
#
# Every glyph below is ASCII or comes from a rich primitive. The development
# terminal reports cp1252, where a box-drawing character raises
# UnicodeEncodeError on write; rich substitutes for its own boxes, but a
# literal here would not be.


def _meter(done: int, total: int, width: int) -> Text:
    """Progress as a drawn bar.

    Two weights of one neutral, filled with background colour rather than
    repeated characters, so the filled span reads as a single continuous
    object. A row of `=` never stops looking like a row of `=`.
    """
    if total <= 0:
        return Text(" " * width, style="on grey23")
    filled = max(0, min(width, round(width * done / total)))
    bar = Text()
    bar.append(" " * filled, style=f"on {PASS}")
    bar.append(" " * (width - filled), style="on grey23")
    return bar


def _title(snapshot: Snapshot) -> Text:
    """The collection's own name, and its meter."""
    line = Text()
    line.append(snapshot.experiment_id, style=f"bold {TEXT}")
    line.append("   ")
    line.append_text(_meter(snapshot.finished, snapshot.total, 22))

    minutes, seconds = divmod(int(snapshot.elapsed_s), 60)
    line.append(f"   {minutes}:{seconds:02d}", style=TEXT_FAINT)
    return line


def _status_line(snapshot: Snapshot) -> Text:
    """What the collection is doing this instant.

    While a run executes this names it, because "which run is this" is the
    question an operator watching a live collection actually has. A finished
    collection says so once rather than leaving a stale in-progress line.
    """
    line = Text()
    current = snapshot.current()
    if current is not None:
        line.append("running   ", style=LIVE)
        line.append(f"{current.arm} ", style=f"bold {arm_style(current.arm)}")
        line.append(current.task_id, style=TEXT_MUTED)
        line.append(f" {current.short_id}", style=TEXT_MUTED)
    elif snapshot.complete:
        line.append("complete  ", style=PASS)
        line.append(f"{snapshot.total} runs recorded", style=TEXT_MUTED)
    else:
        line.append("idle      ", style=TEXT_MUTED)
        line.append(f"{snapshot.counts.get('PLANNED', 0)} planned", style=TEXT_MUTED)

    if not snapshot.reproducible:
        line.append("   not reproducible", style=f"bold {DENIAL}")
        line.append(" - driven by a live agent", style=TEXT_MUTED)
    return line


def _rate_style(passed: int, known: int) -> str:
    """Uniform outcomes read neutral-positive or negative; a split reads warm.

    The mixed case is the interesting one, so it gets the accent rather than
    a third arbitrary hue.
    """
    if not known:
        return "grey54"
    ratio = passed / known
    return PASS if ratio == 1 else (FAIL if ratio == 0 else DENIAL)


def _arm_table(snapshot: Snapshot) -> Table:
    """The comparison: one row per arm, stating what it bought and cost.

    Four arms differing by one factor at a time is a table with four rows,
    not a log with twenty-four lines.
    """
    table = Table(box=None, pad_edge=False, header_style=TEXT_FAINT, expand=True)
    table.add_column("arm", width=4, no_wrap=True)
    table.add_column("condition", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("passed", justify="right", width=7, no_wrap=True)
    table.add_column("rate", justify="right", width=5, no_wrap=True)
    # Costs right-aligned so digits line up by magnitude: comparing 361
    # against 196 should be visible in the column, not read off the numbers.
    table.add_column("bytes/run", justify="right", width=9, no_wrap=True)
    table.add_column("refused", justify="right", width=7, no_wrap=True)

    for arm_id, arm in snapshot.by_arm().items():
        known = len(arm.known)
        condition = Text(ARM_CONDITION.get(arm_id, ""), style=TEXT_MUTED)
        mean = arm.mean_bytes
        table.add_row(
            Text(arm_id, style=f"bold {arm_style(arm_id)}"),
            condition,
            Text(f"{arm.passed}/{known}" if known else "-", style="white"),
            Text(f"{arm.passed / known:.0%}" if known else "-", style=_rate_style(arm.passed, known)),
            Text(f"{mean:,.0f}" if mean is not None else "-", style="white"),
            Text(
                str(arm.denials) if arm.denials else "-",
                style=DENIAL if arm.denials else "grey35",
            ),
        )
    return table


def _task_breakdown(snapshot: Snapshot) -> Table | None:
    """Per-task outcomes, for the arms whose behaviour is not uniform.

    Shown only when an arm actually splits. A breakdown that is always
    present is one more table to scan; one that appears when there is
    something to see is a finding.
    """
    split_arms = {arm_id: arm for arm_id, arm in snapshot.by_arm().items() if arm.splits()}
    if not split_arms:
        return None

    table = Table(box=None, pad_edge=False, header_style=TEXT_FAINT, expand=True)
    table.add_column("", width=4, no_wrap=True)
    table.add_column("task", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("passed", justify="right", width=7, no_wrap=True)
    table.add_column("refused", justify="right", width=7, no_wrap=True)

    for arm_id, arm in split_arms.items():
        for index, (task_id, runs) in enumerate(arm.tasks().items()):
            known = [run for run in runs if run.succeeded is not None]
            passed = sum(1 for run in known if run.succeeded)
            denials = sum(run.denials for run in runs)
            table.add_row(
                Text(arm_id if index == 0 else "", style=f"bold {arm_style(arm_id)}"),
                Text(task_id, style=TEXT_MUTED),
                Text(
                    f"{passed}/{len(known)}" if known else "-",
                    style=_rate_style(passed, len(known)),
                ),
                Text(
                    str(denials) if denials else "-",
                    style=DENIAL if denials else "grey35",
                ),
            )
    return table


def _active_runs(snapshot: Snapshot) -> Table | None:
    """Runs still in flight, while any remain.

    Detail an operator wants during a collection and never after one, so it
    is present exactly then. A finished collection has nothing here and the
    section disappears rather than rendering an empty frame.
    """
    pending = [run for run in snapshot.runs if run.active]
    if not pending:
        return None

    table = Table(box=None, pad_edge=False, header_style=TEXT_FAINT, expand=True)
    table.add_column("", width=4, no_wrap=True)
    table.add_column("task", ratio=1, no_wrap=True, overflow="ellipsis")
    table.add_column("run", width=6, no_wrap=True)
    table.add_column("state", justify="right", width=9, no_wrap=True)

    # Running first: the live one is what the operator is looking for.
    ordered = sorted(pending, key=lambda r: (r.state != "RUNNING", r.arm, r.run_id))
    for run in ordered[:6]:
        table.add_row(
            Text(run.arm, style=f"bold {arm_style(run.arm)}"),
            Text(run.task_id, style=TEXT_MUTED),
            Text(run.short_id, style=TEXT_MUTED),
            Text(run.state.lower(), style=STATE_STYLE.get(run.state, "white")),
        )
    if len(ordered) > 6:
        table.add_row(
            Text(""), Text(f"+{len(ordered) - 6} more planned", style=TEXT_FAINT), Text(""), Text("")
        )
    return table


def _totals(snapshot: Snapshot) -> Text:
    """Running totals, in the project's own terms."""
    line = Text()
    line.append(f"{snapshot.total_bytes:,}", style=f"bold {TEXT}")
    line.append(" coordination bytes", style=TEXT_MUTED)

    line.append("      ")
    denials = snapshot.total_denials
    line.append(str(denials), style=f"bold {DENIAL}" if denials else "bold white")
    line.append(" write refused" if denials == 1 else " writes refused", style=TEXT_MUTED)

    if snapshot.connectors:
        usable = [c["name"] for c in snapshot.connectors if c.get("usable")]
        line.append("      ")
        line.append(", ".join(usable) if usable else "no agents", style=TEXT_MUTED)
    return line


def _finding(snapshot: Snapshot) -> Text:
    """Name the split in a sentence, above the table that evidences it.

    An earlier version marked the split inside the arm row, where it had to
    share a ratio column and truncated to "differs by ..." at 80 columns —
    a finding rendered as a rendering fault. Given its own line it fits at
    every width and can say which arms it is about.
    """
    split = [arm_id for arm_id, arm in snapshot.by_arm().items() if arm.splits()]
    line = Text()
    for index, arm_id in enumerate(split):
        if index:
            line.append(", ", style=TEXT_FAINT)
        line.append(arm_id, style=f"bold {arm_style(arm_id)}")
    line.append(" behaves differently by task", style=TEXT_MUTED)
    return line


def _section(label: str) -> Text:
    """A section heading, set as a heading rather than as a comment.

    Letter-spaced small caps were tried first and rejected: at terminal
    sizes the gaps read as broken words rather than as a heading. Weight
    and a dimmer hue carry the same "new part of the page" without costing
    legibility.
    """
    return Text(label.upper(), style=f"bold {TEXT_FAINT}")


def _masthead(snapshot: Snapshot, width: int, unicode_ok: bool) -> RenderableType:
    """The band across the top: what this is, and how far it has got.

    A page needs a masthead more than a monitor needs a title bar. The
    product name sits left, the collection's progress right, and a rule
    under both separates the identity of the tool from the state of the
    run — which is the distinction a reader loses when both are one line.
    """
    done, total = snapshot.finished, snapshot.total

    left = Text()
    left.append("causalmesh", style=f"bold {TEXT}")
    left.append("  coordination you can prove", style=TEXT_FAINT)

    right = Text()
    right.append(f"{done}", style=f"bold {TEXT}")
    right.append(f"/{total}", style=TEXT_MUTED)
    right.append(" runs", style=TEXT_FAINT)

    # One space minimum, and the right block is dropped entirely rather
    # than wrapped if the terminal is too narrow to hold both: a masthead
    # that folds onto a second line stops being a masthead.
    gap = width - len(left.plain) - len(right.plain)
    band = Text()
    band.append_text(left)
    if gap >= 2:
        band.append(" " * gap)
        band.append_text(right)

    rule = ("─" if unicode_ok else "-") * width
    return Group(band, Text(rule, style=TEXT_FAINT))


# Panel border (2) plus its horizontal padding (2 each side).
PANEL_CHROME = 6


def render(
    snapshot: Snapshot, *, console: Console | None = None, width: int | None = None
) -> RenderableType:
    """The whole frame.

    Takes the console so the masthead can be laid out against the width it
    will actually be given. Measuring is not optional here: the band is
    justified to both edges, and a guessed width folds it onto a second
    line, which is what "24/24 runs" wrapping mid-phrase looked like.
    """
    if width is None:
        width = (console.width if console is not None else 80) - PANEL_CHROME
    unicode_ok = supports_unicode(console) if console is not None else True
    blocks: list[RenderableType] = [
        _masthead(snapshot, width, unicode_ok),
        Text(),
        _title(snapshot),
        _status_line(snapshot),
        Text(),
        _section("arms"),
        _arm_table(snapshot),
    ]

    breakdown = _task_breakdown(snapshot)
    if breakdown is not None:
        blocks += [Text(), _section("where they differ"), _finding(snapshot), breakdown]

    active = _active_runs(snapshot)
    if active is not None:
        blocks += [Text(), _section("in flight"), active]

    blocks += [Text(), _section("totals"), _totals(snapshot)]

    return Panel(
        Group(*blocks),
        border_style=TEXT_FAINT,
        padding=(1, 2),
        title=Text("causalmesh", style=TEXT_MUTED),
        title_align="left",
    )
