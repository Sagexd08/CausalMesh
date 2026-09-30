"""An agent controls the resource name a human is asked to approve.

The name comes from the agent's own tool arguments. If a prompt printed it
raw, an agent could use terminal control sequences to repaint the screen so
the person approves something other than what is being asked, or to smuggle a
fake "already approved" line into the output. The handler writes ASCII only
and shows every other character as a visible escape.
"""

from __future__ import annotations

import io

import pytest

from causalmesh.policy import Checkpoint, Resource, TerminalCheckpointHandler
from causalmesh.policy.terminal_handler import ascii_escape

pytestmark = pytest.mark.adversarial

CHECKPOINT = Checkpoint(on="path", require="human")

HOSTILE = [
    "src/a.py\x1b[2J\x1b[H",  # clear screen, cursor home
    "x\x1b]0;approved\x07",  # retitle the window
    "a\rAPPROVED: nothing to see",  # carriage return rewrites the line
    "a\nagent:    trusted-agent\nresource: README.md",  # forged lines
    "a\x08\x08\x08safe",  # backspaces
    "caf\u00e9/\u202eexe.py",  # non-ASCII, right-to-left override
    "emoji/\U0001f600.py",
    "back\\x1b[31mslash",  # an agent-written escape must not look like ours
    "a\x00b\x7f",
]


def run(resource_name: str, *, agent: str = "agent_a") -> tuple[bool, str, str]:
    out = io.StringIO()
    h = TerminalCheckpointHandler(input_stream=io.StringIO("no\n"), output_stream=out)
    approved, reason = h.decide(
        agent_id=agent, resource=Resource.path(resource_name), checkpoint=CHECKPOINT, now_us=1
    )
    return approved, reason, out.getvalue()


@pytest.mark.parametrize("name", HOSTILE)
def test_output_is_printable_ascii_only(name: str) -> None:
    _, reason, shown = run(name)
    for text in (shown, reason):
        bad = [c for c in text if not (c == "\n" or 0x20 <= ord(c) <= 0x7E)]
        assert bad == [], f"unescaped characters leaked: {bad!r}"


@pytest.mark.parametrize("name", HOSTILE)
def test_a_name_cannot_add_lines_to_the_question(name: str) -> None:
    _, _, shown = run(name)
    lines = shown.splitlines()
    # Exactly one line per field the handler wrote, whatever the name contained.
    assert sum(line.startswith("resource: ") for line in lines) == 1
    assert sum(line.startswith("agent:") for line in lines) == 1
    assert sum("checkpoint #" in line for line in lines) == 1


def test_an_ansi_escape_is_shown_as_text_not_executed() -> None:
    _, _, shown = run("src/a.py\x1b[2J")
    assert "\x1b" not in shown
    assert "\\x1b" in shown


def test_a_hostile_agent_id_is_escaped_too() -> None:
    _, _, shown = run("src/a.py", agent="evil\x1b[31m\nresource: ok")
    assert "\x1b" not in shown
    assert sum(line.startswith("resource: ") for line in shown.splitlines()) == 1


def test_an_agent_written_escape_is_distinguishable_from_the_handlers() -> None:
    assert ascii_escape("\\x1b") == "\\\\x1b"
    assert ascii_escape("\x1b") == "\\x1b"


def test_a_huge_name_cannot_push_the_question_off_the_screen() -> None:
    _, _, shown = run("a/" + "b" * 100_000)
    assert len(shown) < 2_000
    assert "characters)" in shown


def test_a_hostile_name_does_not_change_the_decision_rules() -> None:
    approved, _, _ = run("src/a.py\x1b[2J")
    assert approved is False  # the scripted answer was "no"
