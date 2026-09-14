"""Shared output helpers for the CLI (spec §62).

Two rules the whole CLI follows:

**Every command can emit JSON.** A human reads the table; a script reads
`--json`. Making the machine path an afterthought is how CLIs end up
scraped with `grep`, and a scraped CLI can never change its wording.

**Exit codes carry meaning.** §62 requires actionable exits, so a caller
can branch on the result without parsing anything at all.
"""

from __future__ import annotations

import json
from enum import IntEnum
from typing import Any

from rich.console import Console
from rich.table import Table

# stderr, so `causalmesh ... --json > out.json` stays valid JSON even when
# something is written for the operator at the same time.
err_console = Console(stderr=True)
out_console = Console()


class Exit(IntEnum):
    """Exit codes, by meaning rather than by position.

    `FAILED` and `ERROR` are deliberately distinct: a verification that ran
    correctly and found a bad chain is not the same event as a verifier
    that could not run, and a CI job should be able to tell them apart.
    """

    OK = 0
    FAILED = 1  # the command ran; the answer is negative
    USAGE = 2  # the invocation was wrong
    ERROR = 3  # the command could not complete


def emit(payload: dict[str, Any] | list[Any], *, as_json: bool) -> bool:
    """Print `payload` as JSON when asked. Returns whether it did.

    Callers use the return value to skip their human-readable rendering,
    which keeps the two paths from drifting apart in a long if/else.
    """
    if not as_json:
        return False
    out_console.print_json(json.dumps(payload, default=str))
    return True


def fail(message: str, *, hint: str = "") -> None:
    """Report a problem to the operator, with what to do about it."""
    err_console.print(f"[bold red]error[/bold red] {message}")
    if hint:
        err_console.print(f"        [dim]{hint}[/dim]")


def warn(message: str) -> None:
    err_console.print(f"[bold yellow]warning[/bold yellow] {message}")


def note(message: str) -> None:
    err_console.print(f"[dim]{message}[/dim]")


def table(title: str, columns: list[str]) -> Table:
    t = Table(title=title, title_justify="left", header_style="bold")
    for column in columns:
        t.add_column(column)
    return t


def status_text(ok: bool, *, true: str = "PASS", false: str = "FAIL") -> str:
    return f"[green]{true}[/green]" if ok else f"[red]{false}[/red]"
