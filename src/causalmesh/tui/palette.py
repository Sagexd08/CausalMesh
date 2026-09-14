"""One palette, shared by every terminal surface.

**Designed for sixteen colours, not for truecolor.** The terminal this ships
into reports `color_system: windows`, where rich collapses `grey70`,
`grey62`, `grey54`, `grey42` and `grey30` onto the *same* escape code. An
earlier version of these screens carried a five-step grey hierarchy that was
entirely invisible on the machine it was written on: every dim thing looked
identical, and the tonal structure existed only in the source.

So structure is carried by **hue and weight**, which survive the downgrade,
rather than by tone, which does not. Fifteen colours stay distinct at 16
colours; these are chosen from that set and named for the job they do, so a
surface asks for `RESULT_PASS` rather than for a colour and the meaning
stays consistent across screens.

**Roles, not shades.** A name here says what a thing *is*. That is what lets
the monitor and the welcome screen read as one product without either of
them importing the other's layout.
"""

from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

# -- text ------------------------------------------------------------------
# Three weights of neutral, and no more: a fourth would be indistinguishable
# from one of these on a 16-colour terminal.
TEXT = "bright_white"  # the thing you are reading
TEXT_MUTED = "white"  # supporting detail, still legible
TEXT_FAINT = "bright_black"  # structure, labels, rules — present, not read

# -- meaning ---------------------------------------------------------------
# The experiment's own vocabulary. `DENIAL` is the accent: enforcement
# refusing a write is the only thing this system measures that has a colour,
# so it gets the warmest one and nothing else competes for it.
DENIAL = "bright_yellow"
RESULT_PASS = "bright_green"
RESULT_FAIL = "bright_red"
LIVE = "bright_cyan"
PLANNED = "bright_black"

# -- identity --------------------------------------------------------------
# Arms are the experiment's four conditions and appear on every screen, so
# they get stable hues. Ordered as a gradient of involvement: none, full,
# bounded, bounded plus enforcement.
# C3 is deliberately NOT the denial colour, even though it is the enforcing
# arm. Sharing that hue made the refused agent and the refusal itself one
# mark, so the accent stopped meaning "a write was refused" and started
# meaning "something to do with C3". Magenta keeps the arm identifiable
# while leaving the accent to say one thing.
ARM_COLORS = {
    "C0": "bright_red",
    "C1": "bright_blue",
    "C2": "bright_green",
    "C3": "bright_magenta",
}

# -- surface ---------------------------------------------------------------
BORDER = "bright_black"
HEADING = "bright_white"
LINK = "bright_cyan"

THEME = Theme(
    {
        "cm.arm.c0": ARM_COLORS["C0"],
        "cm.arm.c1": ARM_COLORS["C1"],
        "cm.arm.c2": ARM_COLORS["C2"],
        "cm.arm.c3": ARM_COLORS["C3"],
        "cm.border": BORDER,
        "cm.denial": f"bold {DENIAL}",
        "cm.faint": TEXT_FAINT,
        "cm.fail": RESULT_FAIL,
        "cm.heading": f"bold {HEADING}",
        "cm.live": LIVE,
        "cm.muted": TEXT_MUTED,
        "cm.pass": RESULT_PASS,
        "cm.text": TEXT,
    }
)


def arm_style(arm: str) -> str:
    """The colour that names one arm, everywhere it appears."""
    return ARM_COLORS.get(arm, TEXT_MUTED)


def console(**kwargs) -> Console:
    """A console carrying this palette.

    `theme` rather than inline styles so a surface names a role and the
    palette decides what that looks like here.
    """
    kwargs.setdefault("theme", THEME)
    return Console(**kwargs)


def supports_unicode(target: Console) -> bool:
    """Whether this console can encode the drawn glyphs.

    Asked of the console rather than inferred from the platform: the same
    machine answers differently in Windows Terminal and in a piped cp1252
    stream, and only one of those can render a block character. Rich's
    `safe_box` substitution covers panel and table borders only — not
    `Rule`, and not text handed to it — so every surface that draws has to
    ask this first.
    """
    encoding = target.encoding or "utf-8"
    try:
        "█▓│┴─".encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True
