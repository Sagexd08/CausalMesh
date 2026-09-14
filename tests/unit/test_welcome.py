"""The first-run screen and its check sequence.

The load-bearing property here is glyph safety. The terminal this was built
for reports cp1252, where a block-drawing character raises
`UnicodeEncodeError` — and rich's `safe_box` substitution covers only panel
and table borders, not `Rule` and not text it is handed. Both of those took
the screen down during development, so both are tested against a console
that genuinely cannot encode them rather than against a mock.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from rich.console import Console

from causalmesh.tui import welcome
from causalmesh.tui.onboard import Sequence, Step, build_sequence, run

pytestmark = [pytest.mark.unit]

REPO = Path(__file__).resolve().parents[2]


def cp1252_console(width: int = 80) -> tuple[Console, io.TextIOWrapper]:
    """A console that will actually raise on a block-drawing character."""
    buffer = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    return Console(file=buffer, width=width), buffer


def utf8_console(width: int = 80) -> tuple[Console, io.TextIOWrapper]:
    buffer = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="strict")
    return Console(file=buffer, width=width), buffer


def drain(buffer: io.TextIOWrapper, encoding: str) -> str:
    buffer.flush()
    return buffer.buffer.getvalue().decode(encoding)


class TestGlyphSafety:
    def test_a_cp1252_console_is_detected_as_unable(self) -> None:
        console, _ = cp1252_console()
        assert welcome.supports_blocks(console) is False

    def test_a_utf8_console_is_detected_as_able(self) -> None:
        console, _ = utf8_console()
        assert welcome.supports_blocks(console) is True

    def test_the_whole_screen_renders_on_cp1252(self) -> None:
        """The regression that matters.

        Two separate things crashed here during development: the scene's
        block characters, and `Rule`, which draws with a box-drawing glyph
        and is not covered by rich's safe_box.
        """
        console, buffer = cp1252_console()
        console.print(welcome.render(console))
        output = drain(buffer, "cp1252")

        assert "Welcome to CausalMesh" in output
        assert "src/config.py" in output
        assert "REFUSED" in output
        # The rule degraded rather than crashing.
        assert "---" in output

    def test_the_whole_screen_renders_on_utf8(self) -> None:
        console, buffer = utf8_console()
        console.print(welcome.render(console))
        output = drain(buffer, "utf-8")
        assert "█" in output  # the block-drawn agents
        assert "─" in output  # the box-drawing rule

    def test_the_ascii_scene_is_drawn_not_transliterated(self) -> None:
        """The fallback has to read as a diagram, not as damage."""
        ascii_scene = "\n".join(welcome._draw_scene(block=False))
        assert "[##]" in ascii_scene
        assert "+-----" in ascii_scene
        # And carries no character a cp1252 console would refuse.
        ascii_scene.encode("cp1252")


class TestScene:
    def test_every_agent_label_is_centred_under_its_body(self) -> None:
        """Hand-counted spacing drifts; the grid is computed.

        The first version of this drawing had every name off-centre from
        its own body, which is what generating it fixes.
        """
        for block in (True, False):
            lines = welcome._draw_scene(block)
            bodies, names = lines[0], lines[1]
            for column in welcome.AGENT_COLUMNS:
                # Both rows have a non-space character at the agent's column.
                assert bodies[column] != " "
                assert names[column] != " "

    def test_three_writes_converge_and_one_does_not(self) -> None:
        """The picture states the mechanism: only the fourth is refused."""
        lines = welcome._draw_scene(block=False)
        joined = "\n".join(lines)
        assert "REFUSED" in joined
        # The refused agent's line terminates rather than reaching the file.
        stop_row = lines[4]
        assert stop_row[welcome.AGENT_COLUMNS[3]] == "x"

    def test_the_scene_fits_eighty_columns(self) -> None:
        for block in (True, False):
            assert max(len(line) for line in welcome._draw_scene(block)) <= 80

    def test_the_accent_lands_only_on_the_refusal(self) -> None:
        """One warm mark on the screen, spent on what the experiment measures.

        REFUSED and the filename share a row; styling the whole line painted
        the filename in the denial accent too.
        """
        scene = welcome._scene(Console(width=80))

        # Asserted through rich's own style spans rather than through ANSI
        # codes: the exact escape depends on the terminal's colour depth,
        # and pinning it would make this test about the capture, not the
        # design.
        spans = {
            scene.plain[span.start : span.end]: str(span.style) for span in scene.spans
        }
        # The accent means one thing: a write was refused. C3 is the
        # enforcing arm and was briefly given the same hue, which made the
        # refused agent and the refusal itself indistinguishable.
        accented = [
            scene.plain[span.start : span.end]
            for span in scene.spans
            if str(span.style) == f"bold {welcome.ACCENT}"
        ]
        assert accented == ["REFUSED"]
        assert welcome.arm_style("C3") != welcome.ACCENT


class TestChoices:
    def test_exactly_one_option_is_recommended(self) -> None:
        recommended = [c for c in welcome.CHOICES if c.recommended]
        assert len(recommended) == 1

    def test_every_choice_names_a_real_command(self) -> None:
        """A menu that offers a command this build does not have is a lie."""
        from causalmesh.cli.main import app

        registered = {command.name for command in app.registered_commands}
        registered |= {group.name for group in app.registered_groups}
        for choice in welcome.CHOICES:
            verb = choice.command.split()[1]
            assert verb in registered, f"{choice.command} names an unknown command"

    def test_the_selected_option_is_marked(self) -> None:
        console = Console(width=80)
        with console.capture() as capture:
            console.print(welcome.render(console, selected=2))
        output = capture.get()
        # The marker is a chevron where the terminal can draw one.
        assert "2." in output and "1." in output
        marker = "❯" if welcome.supports_blocks(console) else ">"
        assert f"{marker} 2." in output
        assert f"{marker} 1." not in output


class TestSequence:
    def test_the_real_checks_pass_in_this_checkout(self) -> None:
        console, _ = utf8_console()
        sequence = run(build_sequence(REPO), console, animate=False)
        assert sequence.ready is True
        assert all(step.resolved for step in sequence.steps)

    def test_a_probe_that_raises_is_recorded_rather_than_fatal(self) -> None:
        """A first run reports what it found; it never crashes on a check."""

        def explode() -> tuple[bool, str]:
            raise RuntimeError("probe blew up")

        console, _ = utf8_console()
        sequence = run(Sequence(steps=[Step("boom", explode)]), console, animate=False)
        assert sequence.steps[0].ok is False
        assert "RuntimeError" in sequence.steps[0].detail

    def test_an_optional_failure_does_not_block(self) -> None:
        """A missing optional dependency is not a broken install."""
        sequence = Sequence(
            steps=[
                Step("required", lambda: (True, "")),
                Step("optional", lambda: (False, "absent"), optional=True),
            ]
        )
        console, _ = utf8_console()
        run(sequence, console, animate=False)
        assert sequence.ready is True
        assert len(sequence.warnings) == 1

    def test_a_required_failure_blocks(self) -> None:
        sequence = Sequence(steps=[Step("required", lambda: (False, "missing"))])
        console, _ = utf8_console()
        run(sequence, console, animate=False)
        assert sequence.ready is False
        assert len(sequence.failures) == 1

    def test_the_checks_still_run_without_animation(self) -> None:
        """The sequence is the work, so turning off motion must not turn
        off the checks — that is what makes it safe in CI and in a pipe."""
        calls: list[str] = []

        def probe() -> tuple[bool, str]:
            calls.append("ran")
            return True, "ok"

        console, buffer = cp1252_console()
        run(Sequence(steps=[Step("check", probe)]), console, animate=False)
        assert calls == ["ran"]
        assert "check" in drain(buffer, "cp1252")


class TestPalette:
    """The palette has to survive the terminal it actually ships into.

    That terminal reports `color_system: windows`, where rich collapses
    grey70, grey62, grey54, grey42 and grey30 onto one escape code. An
    earlier version of these screens carried a five-step grey hierarchy
    that was entirely invisible there.
    """

    @staticmethod
    def codes(*styles: str) -> list[str]:
        import re

        buffer = io.StringIO()
        console = Console(
            file=buffer, force_terminal=True, color_system="windows", width=120
        )
        from rich.text import Text

        text = Text()
        for style in styles:
            text.append("X", style=style)
        console.print(text)
        found = re.findall(r"\x1b\[([0-9;]+)m", buffer.getvalue())
        return [code for code in found if code != "0"]

    def test_the_three_text_weights_stay_distinct_at_sixteen_colours(self) -> None:
        from causalmesh.tui import palette

        emitted = self.codes(palette.TEXT, palette.TEXT_MUTED, palette.TEXT_FAINT)
        assert len(set(emitted)) == 3, f"text weights collapsed: {emitted}"

    def test_every_semantic_role_stays_distinct(self) -> None:
        from causalmesh.tui import palette

        roles = [
            palette.DENIAL,
            palette.RESULT_PASS,
            palette.RESULT_FAIL,
            palette.LIVE,
            palette.TEXT,
        ]
        emitted = self.codes(*roles)
        assert len(set(emitted)) == len(roles), f"roles collapsed: {emitted}"

    def test_the_four_arms_stay_distinct(self) -> None:
        """Arm colour is identity; two arms sharing a hue is a misread row."""
        from causalmesh.tui import palette

        emitted = self.codes(*[palette.arm_style(a) for a in ("C0", "C1", "C2", "C3")])
        assert len(set(emitted)) == 4, f"arms collapsed: {emitted}"

    def test_an_unknown_arm_falls_back_rather_than_raising(self) -> None:
        from causalmesh.tui import palette

        assert palette.arm_style("C9") == palette.TEXT_MUTED


class TestChoosing:
    """The menu said "Pick a number" and then exited.

    A UI that makes a promise it does not keep is worse than one that says
    nothing, so the prompt is tested for both halves: that it returns what
    was picked, and that it can always be escaped.
    """

    def test_a_number_returns_the_choice_it_names(self) -> None:
        from unittest.mock import patch

        console = Console(force_terminal=True, width=80)
        with patch("rich.prompt.Prompt.ask", return_value="3"):
            choice = welcome.choose(console)
        assert choice is welcome.CHOICES[2]

    def test_ctrl_c_leaves_rather_than_looping(self) -> None:
        """A first-run screen that cannot be escaped is a trap."""
        from unittest.mock import patch

        console = Console(force_terminal=True, width=80)
        with patch("rich.prompt.Prompt.ask", side_effect=KeyboardInterrupt):
            assert welcome.choose(console) is None

    def test_end_of_input_leaves(self) -> None:
        from unittest.mock import patch

        console = Console(force_terminal=True, width=80)
        with patch("rich.prompt.Prompt.ask", side_effect=EOFError):
            assert welcome.choose(console) is None

    def test_a_non_interactive_stream_does_not_block(self) -> None:
        """Piped output should print the menu and exit, not wait forever."""
        console, _ = utf8_console()
        assert console.is_terminal is False
        assert welcome.choose(console) is None


class TestDiscoverySpeed:
    def test_probes_run_concurrently(self) -> None:
        """Measured: sequential discovery cost 12.9s of which 11s was two
        Node CLIs that take seconds to print their own version. They are
        independent and blocked on process startup, so they run together.
        """
        import time

        from causalmesh.connectors.discovery import ToolSpec, discover

        slow = tuple(
            ToolSpec(f"slow{index}", "infra", sys.executable, version_args=("-c", SLOW))
            for index in range(4)
        )
        started = time.monotonic()
        discover(slow)
        elapsed = time.monotonic() - started

        # Four 0.4s probes: ~1.6s sequential, well under 1s together. The
        # bound is loose because CI machines are slow, but it cannot pass
        # if they ran one after another.
        assert elapsed < 1.2, f"probes appear sequential: {elapsed:.2f}s"

    def test_order_is_preserved_regardless_of_finish_order(self) -> None:
        """A list that reshuffles between runs is harder to read than a
        slow one."""
        from causalmesh.connectors.discovery import AGENT_SPECS, discover

        names = [probe.name for probe in discover(AGENT_SPECS)]
        assert names == [spec.name for spec in AGENT_SPECS]


SLOW = "import time; time.sleep(0.4); print('1.0.0')"
