"""The first-run screen: a title, a scene, and the choice that starts you.

The shape is the one a first run wants — a titled banner, a rule, a drawn
scene, a line telling you where you are, then a numbered list you actually
pick from. Nothing here is a splash: the scene states what the product is
about, and the list is the only way to leave the screen.

**The scene draws the product's own subject.** Four agents reaching for one
shared file, with the write gate between them — which is the entire
experiment in one picture. Borrowed mascots and generic terminal art would
say nothing a reader could use; this says what C3 does before a single
table appears.

**Glyph safety is load-bearing.** The terminal this was built for reports
cp1252, where a block-drawing character raises `UnicodeEncodeError` on
write — and rich substitutes only for its own box characters, not for text
it is handed. So the scene exists twice: a block-drawn version for terminals
that can encode it, and a hand-drawn ASCII version that is a real drawing
rather than a degraded one. The fallback is chosen by asking the console
whether it can encode the glyph, never by guessing from the platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.rule import Rule
from rich.text import Text

from causalmesh.tui.palette import (
    DENIAL as ACCENT,
    LIVE,
    RESULT_PASS as PASS,
    TEXT,
    TEXT_FAINT as DIM,
    TEXT_MUTED,
    arm_style,
    supports_unicode,
)

# The scene is generated on a column grid rather than typed as literal
# lines. Hand-counted spacing drifts the moment a label changes length, and
# the first version of this drawing had every agent name off-centre from its
# own body for exactly that reason.
SCENE_WIDTH = 62
AGENT_COLUMNS = (7, 19, 31, 53)
AGENT_NAMES = ("agent_a", "agent_b", "agent_c", "agent_d")
CONTESTED_FILE = " src/config.py "

# The one warm mark on the screen, spent on the thing the experiment
# measures: the write that was refused.
ACCENT_MARKERS = ("REFUSED",)
FILE_MARKERS = ("src/config.py",)


def _draw_scene(block: bool) -> list[str]:
    """Three agents whose writes land, and one refused at the gate.

    The whole experiment in one picture: the same information reaches every
    agent, and only C3 stops the fourth write. Drawn twice — once in blocks
    for terminals that can encode them, once in ASCII that is composed for
    ASCII rather than transliterated, so the fallback reads as a diagram
    instead of as damage.
    """
    body = "████" if block else "[##]"
    vertical = "│" if block else "|"
    junction = "┴" if block else "+"
    horizontal = "─" if block else "-"
    corner_left = "└" if block else "+"
    corner_right = "┘" if block else "+"
    wall = "▓" if block else "#"
    stopped = "×" if block else "x"

    def blank() -> list[str]:
        return [" "] * SCENE_WIDTH

    def put(row: list[str], column: int, text: str) -> None:
        for offset, char in enumerate(text):
            if 0 <= column + offset < SCENE_WIDTH:
                row[column + offset] = char

    rows: list[list[str]] = []

    row = blank()
    for column in AGENT_COLUMNS:
        put(row, column - len(body) // 2, body)
    rows.append(row)

    row = blank()
    for column, name in zip(AGENT_COLUMNS, AGENT_NAMES):
        put(row, column - len(name) // 2, name)
    rows.append(row)

    row = blank()
    for column in AGENT_COLUMNS:
        put(row, column, vertical)
    rows.append(row)

    # Three writes converge on the file; the fourth keeps its own line.
    row = blank()
    put(row, AGENT_COLUMNS[0], corner_left)
    for column in range(AGENT_COLUMNS[0] + 1, AGENT_COLUMNS[2]):
        put(row, column, horizontal)
    put(row, AGENT_COLUMNS[2], corner_right)
    put(row, AGENT_COLUMNS[1], junction)
    put(row, AGENT_COLUMNS[3], vertical)
    rows.append(row)

    # And stops short of it.
    row = blank()
    put(row, AGENT_COLUMNS[1], vertical)
    put(row, AGENT_COLUMNS[3], stopped)
    rows.append(row)

    left = AGENT_COLUMNS[1] - len(CONTESTED_FILE) // 2
    row = blank()
    put(row, left - 1, wall * (len(CONTESTED_FILE) + 2))
    rows.append(row)

    row = blank()
    put(row, left, CONTESTED_FILE)
    put(row, left - 1, wall)
    put(row, left + len(CONTESTED_FILE), wall)
    put(row, AGENT_COLUMNS[3] - 3, "REFUSED")
    rows.append(row)

    row = blank()
    put(row, left - 1, wall * (len(CONTESTED_FILE) + 2))
    rows.append(row)

    return ["".join(row).rstrip() for row in rows]


@dataclass
class Choice:
    """One numbered option on the first screen."""

    label: str
    detail: str
    command: str
    recommended: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "detail": self.detail,
            "label": self.label,
            "recommended": self.recommended,
        }


CHOICES = (
    Choice(
        command="causalmesh experiment run --profile smoke",
        detail="four arms, one task, about a minute",
        label="Run a smoke collection",
        recommended=True,
    ),
    Choice(
        command="causalmesh analyze --latest",
        detail="what each arm bought, and what it cost",
        label="Read the measured results",
    ),
    Choice(
        command="causalmesh verify --all",
        detail="every chain, offline, with the relay stopped",
        label="Verify the evidence",
    ),
    Choice(
        command="causalmesh connectors list",
        detail="the coding agents installed here",
        label="See what this machine has",
    ),
)


def supports_blocks(console: Console) -> bool:
    """Whether this console can encode the block-drawn scene.

    Delegates to the palette so both surfaces answer the question the same
    way; two independent copies of an encoding check are two chances to
    disagree about what this terminal can draw.
    """
    return supports_unicode(console)


def _scene(console: Console) -> Text:
    """The drawn scene, in whichever material this terminal can render."""
    lines = _draw_scene(supports_blocks(console))

    scene = Text()
    for index, line in enumerate(lines):
        if index:
            scene.append("\n")
        base = "grey62" if "agent_" in line else DIM
        scene.append(line, style=base)

        # REFUSED and the contested filename share a row, so emphasis is
        # applied as a span over the words that earn it rather than as a
        # style over the whole line — which painted the filename in the
        # denial accent and spent the screen's one warm mark twice.
        offset = len(scene) - len(line)
        for markers, style in ((ACCENT_MARKERS, ACCENT), (FILE_MARKERS, "grey70")):
            for marker in markers:
                at = line.find(marker)
                if at >= 0:
                    scene.stylize(style, offset + at, offset + at + len(marker))
    return scene


def _rule(console: Console) -> Rule:
    """A horizontal rule this terminal can actually encode.

    `Rule` draws with a box-drawing character and is NOT covered by rich's
    `safe_box` substitution, which applies to panel and table borders only.
    On the cp1252 console this was built for it raises UnicodeEncodeError
    and takes the whole screen down, so the character is chosen the same
    way the scene's material is.
    """
    return Rule(characters="─" if supports_blocks(console) else "-", style=DIM)


def _title(version: str) -> Text:
    line = Text()
    line.append("Welcome to CausalMesh", style=f"bold {ACCENT}")
    line.append(f" v{version}", style=DIM)
    return line


def _lead() -> Group:
    """What the scene just showed, said once in words."""
    first = Text()
    first.append("Four agents, one repository. ", style=TEXT_MUTED)
    first.append("Three writes land; one is refused and recorded.", style=TEXT_MUTED)

    second = Text()
    second.append(
        "This measures what that refusal buys, and what it costs.", style=TEXT_MUTED
    )
    return Group(first, second)


def _choices(selected: int) -> Group:
    """The numbered list, with one option marked as the place to start."""
    rows: list[RenderableType] = []
    for index, choice in enumerate(CHOICES, start=1):
        active = index == selected
        line = Text()
        line.append("> " if active else "  ", style=LIVE if active else DIM)
        line.append(f"{index}. ", style=TEXT_MUTED)
        line.append(choice.label, style=f"bold {PASS}" if active else "white")
        if choice.recommended:
            line.append("  recommended", style=DIM)
        rows.append(line)

        detail = Text("     ")
        detail.append(choice.detail, style=DIM)
        rows.append(detail)
    return Group(*rows)


def _footer() -> Text:
    line = Text()
    line.append("Pick a number", style=TEXT_MUTED)
    line.append(", or press ", style=DIM)
    line.append("Enter", style=TEXT_MUTED)
    line.append(" for the first. ", style=DIM)
    line.append("Ctrl-C", style=TEXT_MUTED)
    line.append(" to leave.", style=DIM)
    return line


def render(console: Console, *, version: str = "0.1.0", selected: int = 1) -> RenderableType:
    """The whole first screen."""
    return Group(
        _title(version),
        _rule(console),
        Text(),
        _scene(console),
        Text(),
        _lead(),
        Text(),
        _rule(console),
        Text(),
        Text("Let's get started.", style=f"bold {TEXT}"),
        Text(),
        _choices(selected),
        Text(),
        _footer(),
    )
