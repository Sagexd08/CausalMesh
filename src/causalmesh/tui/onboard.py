"""First-run sequence: the machine checking itself, shown as it happens.

**The animation is the work.** Every line that resolves here is a real
probe — the interpreter, the signing library, the task suite, the coding
agents installed on this machine — and each takes long enough to be worth
showing. Agent discovery alone invokes several binaries and can run for
seconds. A progress bar over instant work is a lie about how long
something took; a spinner over a probe that genuinely takes two seconds is
just the truth, rendered.

So the sequence has one job: make a wait that already exists legible, and
leave the operator knowing what this machine can and cannot do. It is not
decoration laid over a silent function.

**Motion rules.** One authored moment, not scattered effects. A step is
pending, then live, then resolved, and it never animates again — a screen
where everything is always moving has told you nothing about what is
moving *now*. Resolved steps stay on screen as a record rather than being
cleared, because the point is the summary they accumulate into.

Every glyph is ASCII. The terminal this was built for reports cp1252,
where the usual spinner braille raises `UnicodeEncodeError`, so the
spinner frames are drawn from characters that survive it.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.text import Text

# The palette the monitor uses, so the two surfaces read as one product.
DENIAL = "dark_orange3"
PASS = "green3"
FAIL = "red3"
LIVE = "cyan"

# A spinner that survives cp1252. Braille dots are the rich default and the
# first thing to crash on a Windows console; these are four rotations of an
# ASCII bar, which reads as rotation rather than as flicker.
FRAMES = ("|", "/", "-", "\\")
FRAME_S = 0.09

# Long enough that a resolved step registers as having happened, short
# enough that eight of them do not become a loading screen. Motion that
# conveys state should not make the operator wait for choreography.
SETTLE_S = 0.06


@dataclass
class Step:
    """One check: what it is called, and what it turned out to be."""

    label: str
    probe: Callable[[], tuple[bool, str]]
    detail: str = ""
    ok: bool | None = None
    optional: bool = False
    # Shown while the probe runs. A spinner with no subject makes a slow
    # check look broken; naming the reason makes the same wait legible.
    waiting: str = ""

    @property
    def resolved(self) -> bool:
        return self.ok is not None


@dataclass
class Sequence:
    """The whole first run, and what it concluded."""

    steps: list[Step] = field(default_factory=list)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if s.ok is False and not s.optional]

    @property
    def warnings(self) -> list[Step]:
        return [s for s in self.steps if s.ok is False and s.optional]

    @property
    def ready(self) -> bool:
        return not self.failures


def _wordmark(revealed: int) -> Text:
    """The name, typed in rather than printed.

    One authored moment, spent at the start where it sets the tone and then
    never repeated. `revealed` is a character count, so the reveal is a
    property of the frame rather than a timer inside the renderer.
    """
    name = "causalmesh"
    line = Text()
    line.append(name[:revealed], style="bold white")
    if revealed < len(name):
        # The cursor sits where the next character will land.
        line.append("_", style=LIVE)
    else:
        line.append("  coordination you can prove", style="grey42")
    return line


def _step_line(step: Step, frame: int) -> Text:
    """A step, in one of its three states.

    Pending is dim and marked, live carries the spinner, resolved carries a
    verdict and the detail the probe found. Only the live step moves.
    """
    line = Text("  ")
    if step.ok is None and frame < 0:
        line.append(".", style="grey30")
        line.append(f"  {step.label}", style="grey35")
        return line

    if step.ok is None:
        line.append(FRAMES[frame % len(FRAMES)], style=LIVE)
        line.append(f"  {step.label}", style="white")
        if step.waiting:
            line.append(f"  {step.waiting}", style="grey42")
        return line

    if step.ok:
        line.append("+", style=PASS)
        line.append(f"  {step.label}", style="grey70")
    else:
        # An optional dependency that is missing is not a failure; saying so
        # in the same red as a broken install sends the operator hunting for
        # a problem they do not have.
        line.append("!" if step.optional else "x", style=DENIAL if step.optional else FAIL)
        line.append(f"  {step.label}", style="grey70")

    if step.detail:
        line.append(f"  {step.detail}", style="grey42")
    return line


def _verdict(sequence: Sequence) -> Text:
    """What the operator can do next, named as an action."""
    line = Text()
    if sequence.ready:
        # Deliberately does not name a command: the welcome screen's menu
        # names them, and a verdict that repeats the first option turns the
        # menu into an echo rather than a choice.
        line.append("  ready", style=f"bold {PASS}")
        warnings = len(sequence.warnings)
        if warnings:
            line.append(f"   {warnings} optional check", style="grey54")
            line.append("" if warnings == 1 else "s", style="grey54")
            line.append(" did not pass", style="grey54")
    else:
        line.append("  blocked", style=f"bold {FAIL}")
        failed = ", ".join(step.label for step in sequence.failures)
        line.append(f"   {failed}", style="grey54")
    return line


def _frame(sequence: Sequence, *, revealed: int, active: int, tick: int) -> RenderableType:
    """One rendered frame of the sequence."""
    blocks: list[RenderableType] = [_wordmark(revealed), Text()]
    for index, step in enumerate(sequence.steps):
        if index < active:
            blocks.append(_step_line(step, -1) if not step.resolved else _step_line(step, 0))
        elif index == active:
            blocks.append(_step_line(step, tick))
        else:
            blocks.append(_step_line(step, -1))
    if active >= len(sequence.steps):
        blocks += [Text(), _verdict(sequence)]
    return Group(*blocks)


def build_sequence(root: Any) -> Sequence:
    """The checks a first run performs, in the order they matter.

    Ordered so the cheap structural facts resolve immediately and the slow
    probe — invoking every agent binary on the machine — comes last, where
    the spinner it needs is expected rather than jarring.
    """
    from pathlib import Path

    root = Path(root)

    def python_probe() -> tuple[bool, str]:
        import sys

        version = ".".join(str(part) for part in sys.version_info[:3])
        return sys.version_info[:2] >= (3, 11), version

    def crypto_probe() -> tuple[bool, str]:
        try:
            import cryptography  # noqa: F401
        except ImportError:
            return False, "pip install -e ."
        return True, "Ed25519 signing"

    def tasks_probe() -> tuple[bool, str]:
        try:
            from causalmesh.tasks import load_tasks

            tasks = load_tasks(root / "tasks")
        except Exception as exc:  # noqa: BLE001 — a first run reports, never crashes
            return False, f"{type(exc).__name__}"
        return bool(tasks), f"{len(tasks)} loaded"

    def fixtures_probe() -> tuple[bool, str]:
        directory = root / "fixtures"
        if not directory.is_dir():
            return False, "missing"
        return True, f"{len(list(directory.iterdir()))} available"

    def evidence_probe() -> tuple[bool, str]:
        raw = root / "data" / "raw"
        if not raw.is_dir():
            return True, "none yet"
        collections = [p for p in raw.iterdir() if p.is_dir()]
        if not collections:
            return True, "none yet"
        runs = sum(len([d for d in c.iterdir() if (d / "run.json").is_file()]) for c in collections)
        return True, f"{len(collections)} collections, {runs} runs"

    def agents_probe() -> tuple[bool, str]:
        from causalmesh.connectors.discovery import AGENT_SPECS, discover
        from causalmesh.connectors.process import SPECS

        probes = discover(AGENT_SPECS)
        usable = [p for p in probes if p.usable]
        drivable = [p for p in usable if p.name in SPECS]
        if not usable:
            return False, "none installed"
        names = ", ".join(p.name for p in drivable) or "none drivable"
        return True, f"{len(usable)} found - {names}"

    return Sequence(
        steps=[
            Step("python", python_probe),
            Step("signing", crypto_probe),
            Step("tasks", tasks_probe),
            Step("fixtures", fixtures_probe),
            Step("evidence on disk", evidence_probe, optional=True),
            Step(
                "coding agents",
                agents_probe,
                optional=True,
                # This one really is slow: it starts every agent binary on
                # the machine, and some take six seconds to say their own
                # version. Saying so is better than a spinner that looks
                # stuck.
                waiting="starting each one to check it runs",
            ),
        ]
    )


def _reveal_frames(sequence: Sequence, console: Console) -> Iterator[RenderableType]:
    """The wordmark typing itself in, before any work starts."""
    for revealed in range(len("causalmesh") + 1):
        yield _frame(sequence, revealed=revealed, active=-1, tick=0)


def run(sequence: Sequence, console: Console, *, animate: bool = True) -> Sequence:
    """Execute the sequence, rendering it as it resolves.

    With `animate=False` every probe still runs and every result is still
    printed — the sequence is the work, so turning off the motion must not
    turn off the checks. That is what makes this safe in CI and in a pipe,
    where a spinner would be noise written to a file.
    """
    if not animate or not console.is_terminal:
        for step in sequence.steps:
            try:
                step.ok, step.detail = step.probe()
            except Exception as exc:  # noqa: BLE001 — a first run reports
                step.ok, step.detail = False, f"{type(exc).__name__}"
        console.print(_frame(sequence, revealed=len("causalmesh"), active=len(sequence.steps), tick=0))
        return sequence

    name_length = len("causalmesh")
    with Live(console=console, refresh_per_second=30, transient=False) as live:
        for frame in _reveal_frames(sequence, console):
            live.update(frame)
            time.sleep(FRAME_S / 2)

        for index, step in enumerate(sequence.steps):
            # The probe runs on a worker so the spinner keeps turning while
            # it works. Animating on the same thread that blocks would give
            # a frozen spinner during exactly the wait it exists to cover —
            # the agent probe invokes several binaries and takes seconds.
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(step.probe)
                tick = 0
                while not future.done():
                    live.update(_frame(sequence, revealed=name_length, active=index, tick=tick))
                    tick += 1
                    time.sleep(FRAME_S)
                try:
                    step.ok, step.detail = future.result()
                except Exception as exc:  # noqa: BLE001 — a first run reports
                    step.ok, step.detail = False, f"{type(exc).__name__}"

            live.update(_frame(sequence, revealed=name_length, active=index + 1, tick=0))
            time.sleep(SETTLE_S)

        live.update(_frame(sequence, revealed=name_length, active=len(sequence.steps), tick=0))

    return sequence
