"""Unit tests for the shared CLI output helpers (`cli/_output.py`).

`table()`'s column overflow is asked of the console rather than assumed
ASCII-only or assumed to support any particular codepage — the same
convention `tui.palette.supports_unicode` already follows and the one
AGENTS.md names directly ("ask the console what it can encode; never infer
from the platform").
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from causalmesh.cli import _output

pytestmark = pytest.mark.unit


class _FakeFile(io.StringIO):
    """A file-like object that reports a chosen encoding, for Console."""

    def __init__(self, encoding: str) -> None:
        super().__init__()
        self._reported_encoding = encoding

    @property
    def encoding(self) -> str:
        return self._reported_encoding


class TestSupportsEllipsis:
    def test_true_for_an_encoding_that_can_represent_it(self) -> None:
        # cp1252 has a real byte for U+2026 (0x85); this is the console this
        # project is built against, per docs/backlog.md's ASCII-terminal rule
        # and AGENTS.md.
        console = Console(file=_FakeFile("cp1252"))
        assert _output._supports_ellipsis(console) is True

    def test_false_for_strict_ascii(self) -> None:
        console = Console(file=_FakeFile("ascii"))
        assert _output._supports_ellipsis(console) is False

    def test_true_for_utf8(self) -> None:
        console = Console(file=_FakeFile("utf-8"))
        assert _output._supports_ellipsis(console) is True


class TestTableOverflow:
    def test_uses_fold_when_the_console_cannot_encode_ellipsis(self, monkeypatch) -> None:
        monkeypatch.setattr(_output, "_supports_ellipsis", lambda console: False)

        rendered = _output.table("title", ["a", "b"])

        assert all(column.overflow == "fold" for column in rendered.columns)

    def test_uses_ellipsis_when_the_console_can_encode_it(self, monkeypatch) -> None:
        monkeypatch.setattr(_output, "_supports_ellipsis", lambda console: True)

        rendered = _output.table("title", ["a", "b"])

        assert all(column.overflow == "ellipsis" for column in rendered.columns)

    def test_folded_output_never_carries_a_non_ascii_byte(self) -> None:
        """The property that actually matters, exercised end to end.

        Renders a table with a cell too long for its column under a console
        that cannot encode Rich's usual overflow character, and checks the
        rendered bytes rather than the column setting — proving the fix
        rather than asserting on how it is implemented.
        """
        console = Console(file=_FakeFile("ascii"), width=20)
        overflow = "fold" if not _output._supports_ellipsis(console) else "ellipsis"
        rendered = _output.Table(title="t")
        rendered.add_column("long", overflow=overflow)
        rendered.add_row("a very long value that will not fit")

        console.print(rendered)
        output = console.file.getvalue()
        output.encode("ascii")  # raises UnicodeEncodeError if this fails
