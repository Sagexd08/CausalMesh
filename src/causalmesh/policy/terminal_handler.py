"""A human-attached `CheckpointHandler`: ask a person at a terminal.

`AutoDenyHandler` refuses every checkpoint because an unattended run cannot
honor `require: human`. This is the handler for when someone *is* attached.
It satisfies the same synchronous `decide(...) -> (bool, str)` protocol, so
the gate is unchanged and nothing here is a second authorization path.

**The default is refusal, at every failure.** A checkpoint exists so that a
person says yes. Anything short of a clear "yes" from a person who was
actually shown the question is a no: end of input, a closed stream, a missing
terminal when one was required, a timeout, an answer that is not yes or no
after a bounded number of tries, or an output stream that could not show the
question at all. None of these is ever read as approval.

**It never blocks forever.** The read happens on a daemon thread and the
caller waits on a queue with a deadline. A reader thread that outlives its
deadline is remembered, and the one line it eventually reads is discarded: an
answer typed late belongs to a question that has already been refused, and
must not be taken as the answer to the next one.

**Output is ASCII, and what the agent controls is escaped.** The resource name
comes from the agent's tool arguments. Printed raw, an escape sequence in it
could repaint the screen to show the human a question that is not the one
being asked. Every character outside printable ASCII, and the backslash
itself, is written as a visible escape (`\\x1b`), so the name can be read but
not executed. The same rule keeps Windows consoles that default to cp1252
from raising `UnicodeEncodeError` mid-prompt.

**One question at a time.** Agents may call from several threads; a lock
keeps their prompts from interleaving so each answer belongs to the question
printed just above it.

**What this does not make reproducible.** A person's answers are not a
function of the seed. A run that installs this handler says so
(`deterministic = False`); `ScriptedHandler` is the reproducible one.
"""

from __future__ import annotations

import contextlib
import queue
import sys
import threading
import time
from typing import Any, TextIO

from causalmesh.policy.contract import Checkpoint
from causalmesh.policy.resource import Resource

__all__ = ["TerminalCheckpointHandler", "ascii_escape"]

DEFAULT_TIMEOUT_S = 120.0
DEFAULT_MAX_ATTEMPTS = 3
_MAX_SHOWN = 160

_YES = frozenset({"y", "yes"})
_NO = frozenset({"n", "no"})


def ascii_escape(text: object, *, limit: int = _MAX_SHOWN) -> str:
    """`text` as printable ASCII only, with everything else visibly escaped.

    Control characters, ANSI escapes, newlines and non-ASCII characters
    become `\\xNN`, `\\uNNNN` or `\\UNNNNNNNN`; a literal backslash doubles so
    an escape written by the agent cannot be mistaken for one written here.
    Long values are cut at `limit` characters of output with the original
    length stated, so a huge name cannot push the question off the screen.
    """
    pieces: list[str] = []
    for char in str(text):
        code = ord(char)
        if char == "\\":
            pieces.append("\\\\")
        elif 0x20 <= code <= 0x7E:
            pieces.append(char)
        elif code <= 0xFF:
            pieces.append(f"\\x{code:02x}")
        elif code <= 0xFFFF:
            pieces.append(f"\\u{code:04x}")
        else:
            pieces.append(f"\\U{code:08x}")
    rendered = "".join(pieces)
    if len(rendered) > limit:
        return f"{rendered[:limit]}... ({len(str(text))} characters)"
    return rendered


class TerminalCheckpointHandler:
    """Put a matched checkpoint to a person and return their answer.

    Args:
        input_stream:  Where answers are read. `sys.stdin` when omitted,
                       resolved at first use rather than at construction.
        output_stream: Where the question is written. `sys.stderr` when
                       omitted, so a command's machine-readable stdout is not
                       mixed with prompts.
        require_tty:   Refuse without asking when the input stream is not an
                       interactive terminal. A pipe can answer a prompt, but
                       nobody read the question; set this when "a person is
                       present" is the point.
        timeout_s:     Seconds a person has to answer one checkpoint, across
                       all of its attempts. Must be positive.
        max_attempts:  How many times an unintelligible answer is re-asked
                       before the checkpoint is refused.

    `decisions()` is this handler's own record of what it was asked and what
    it answered, including every refusal that came from a failure rather than
    from a person. It is outside the signed chain and holds no clock of its
    own: `now_us` is whatever the caller passed to the gate.
    """

    deterministic = False

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        require_tty: bool = False,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if not timeout_s > 0:
            raise ValueError(f"timeout_s must be positive, got {timeout_s!r}")
        if max_attempts < 1:
            raise ValueError(f"max_attempts must be at least 1, got {max_attempts!r}")
        self._input = input_stream
        self._output = output_stream
        self._require_tty = require_tty
        self._timeout_s = float(timeout_s)
        self._max_attempts = max_attempts

        self._lock = threading.Lock()
        self._decisions: list[dict[str, Any]] = []
        self._eof = False
        # The one outstanding read, if a deadline passed before it finished.
        self._pending: queue.Queue[str | None] | None = None
        self._pending_is_stale = False

    # ------------------------------------------------------------------ #
    # The protocol                                                        #
    # ------------------------------------------------------------------ #

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]:
        """Ask the person. Approval needs an explicit yes; everything else refuses."""
        with self._lock:
            approved, reason, outcome = self._ask(agent_id, resource, checkpoint)
            self._decisions.append(
                {
                    "agent_id": agent_id,
                    "approved": approved,
                    "checkpoint": checkpoint.to_dict(),
                    "now_us": now_us,
                    "outcome": outcome,
                    "reason": reason,
                    "resource": resource.to_dict(),
                    "sequence": len(self._decisions) + 1,
                }
            )
            return approved, reason

    def decisions(self) -> list[dict[str, Any]]:
        """Every checkpoint this handler decided, in order (copies)."""
        with self._lock:
            return [dict(entry) for entry in self._decisions]

    # ------------------------------------------------------------------ #
    # Asking                                                              #
    # ------------------------------------------------------------------ #

    def _ask(
        self, agent_id: str, resource: Resource, checkpoint: Checkpoint
    ) -> tuple[bool, str, str]:
        required = ascii_escape(checkpoint.require)
        if self._eof:
            return self._refuse("input is closed; refusing", "eof", required)

        stream = self._input if self._input is not None else sys.stdin
        if self._require_tty and not _is_tty(stream):
            return self._refuse("no interactive terminal; refusing", "no_tty", required)

        deadline = time.monotonic() + self._timeout_s
        sequence = len(self._decisions) + 1
        try:
            self._show_question(agent_id, resource, checkpoint, sequence)
        except (OSError, ValueError):
            return self._refuse("could not show the prompt; refusing", "no_output", required)

        for attempt in range(1, self._max_attempts + 1):
            try:
                self._write("Approve? [y/N]: ")
            except (OSError, ValueError):
                return self._refuse("could not show the prompt; refusing", "no_output", required)

            line = self._read_line(stream, deadline)
            if line is _TIMEOUT:
                self._say("\n(no answer in time; refusing)")
                return self._refuse(
                    f"no answer within {self._timeout_s:g}s; refusing", "timeout", required
                )
            if line is None:
                self._eof = True
                self._say("\n(input closed; refusing)")
                return self._refuse("input closed before an answer; refusing", "eof", required)

            answer = str(line).strip().lower()
            if answer in _YES:
                return True, f"approved by a person at the terminal ({required})", "answered"
            if answer in _NO:
                return self._refuse(
                    f"denied by a person at the terminal ({required})", "answered", required
                )
            self._say(f"(please answer y or n; attempt {attempt} of {self._max_attempts})")

        return self._refuse(
            f"no valid answer after {self._max_attempts} attempt(s); refusing",
            "invalid",
            required,
        )

    @staticmethod
    def _refuse(reason: str, outcome: str, required: str) -> tuple[bool, str, str]:
        return False, f"{reason} ({required})", outcome

    def _show_question(
        self, agent_id: str, resource: Resource, checkpoint: Checkpoint, sequence: int
    ) -> None:
        when = ", ".join(
            f"{ascii_escape(key)}={ascii_escape(value)}"
            for key, value in sorted(checkpoint.when.items())
        )
        lines = [
            "",
            f"=== checkpoint #{sequence}: human approval required ===",
            f"agent:    {ascii_escape(agent_id)}",
            f"resource: {ascii_escape(resource.describe())}",
            f"kind:     {ascii_escape(resource.kind.value)}",
            f"rule:     on={ascii_escape(checkpoint.on)}"
            f" require={ascii_escape(checkpoint.require)}" + (f" when {when}" if when else ""),
        ]
        self._write("\n".join(lines) + "\n")

    def _write(self, text: str) -> None:
        stream = self._output if self._output is not None else sys.stderr
        stream.write(text)
        stream.flush()

    def _say(self, text: str) -> None:
        """Best-effort feedback; a failed write never changes a decision."""
        with contextlib.suppress(OSError, ValueError):
            self._write(text + "\n")

    # ------------------------------------------------------------------ #
    # Reading with a deadline                                             #
    # ------------------------------------------------------------------ #

    def _read_line(self, stream: TextIO, deadline: float) -> str | None | object:
        """One line, `None` on end of input, or `_TIMEOUT`.

        At most one reader thread exists at a time, and it reads exactly one
        line, so input that is already waiting (a piped `yes`) is consumed one
        question at a time and not swallowed ahead of its question.
        """
        while True:
            if self._pending is None:
                self._pending = _start_reader(stream)
                self._pending_is_stale = False
            try:
                line = self._pending.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                self._pending_is_stale = True
                return _TIMEOUT
            stale = self._pending_is_stale
            self._pending = None
            self._pending_is_stale = False
            if stale:
                # Typed after its question was refused. Not an answer to this one.
                if line is None:
                    return None
                continue
            return line


class _Timeout:
    def __repr__(self) -> str:
        return "<timeout>"


_TIMEOUT = _Timeout()


def _start_reader(stream: TextIO) -> queue.Queue[str | None]:
    """Read one line on a daemon thread. `None` is end of input or a dead stream."""
    box: queue.Queue[str | None] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            line = stream.readline()
        except Exception:  # noqa: BLE001 - any failure to read is "no answer", never approval
            box.put(None)
            return
        box.put(line if line else None)

    threading.Thread(target=read, name="causalmesh-checkpoint-reader", daemon=True).start()
    return box


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False
