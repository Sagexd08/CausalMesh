"""Checkpoint evaluation: `policy.checkpoints`, made real.

A checkpoint fires when a resource's kind matches `on` and its `when`
clause matches. The decision is delegated to a `CheckpointHandler`, a
synchronous callback, so the gate stays synchronous end to end.
"""

from __future__ import annotations

import re
import sys
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, TextIO

from causalmesh.policy.contract import Checkpoint
from causalmesh.policy.resource import Resource

__all__ = [
    "AutoDenyHandler",
    "CheckpointDecision",
    "CheckpointHandler",
    "ScriptedHandler",
    "TerminalCheckpointHandler",
    "evaluate_checkpoints",
]

_COMPARISON = re.compile(r"^(==|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?)$")


@dataclass(frozen=True, slots=True)
class CheckpointDecision:
    """The outcome of one matched checkpoint."""

    approved: bool
    checkpoint: Checkpoint
    resource: Resource
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "checkpoint": self.checkpoint.to_dict(),
            "reason": self.reason,
            "resource": self.resource.to_dict(),
        }


class CheckpointHandler(Protocol):
    """Decides a matched checkpoint. Synchronous, so evaluation never blocks

    on I/O the gate cannot model.
    """

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]: ...


@dataclass(frozen=True, slots=True)
class AutoDenyHandler:
    """The default: refuse every matched checkpoint.

    A run with no attached human cannot honor `require: human`, and treating
    that as approval would make an unattended run silently skip the
    safeguard it declared.
    """

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]:
        return False, f"no checkpoint handler attached; refusing by default ({checkpoint.require})"


@dataclass(slots=True)
class ScriptedHandler:
    """A deterministic sequence of answers, for tests and reproducible runs."""

    answers: list[bool]
    _index: int = 0

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]:
        if self._index >= len(self.answers):
            raise RuntimeError(
                f"ScriptedHandler exhausted its {len(self.answers)} scripted answer(s) "
                f"on a checkpoint for {agent_id!r}"
            )
        answer = self.answers[self._index]
        self._index += 1
        return answer, f"scripted answer #{self._index}: {'approved' if answer else 'denied'}"


_APPROVE_ANSWERS = frozenset({"y", "yes"})
_PROMPT_FIELD_LIMIT = 160


def _ascii(value: object, *, limit: int = _PROMPT_FIELD_LIMIT) -> str:
    """Render text for a terminal prompt as printable ASCII only.

    Agent ids, paths and hostnames come from the agent's own arguments. Printed
    raw, a newline or an ANSI escape in one could redraw the prompt (a fake
    "approved" line, a hidden field) in front of the person deciding. Every
    other character becomes a visible backslash escape, and the field is cut.
    """
    out: list[str] = []
    for char in str(value):
        code = ord(char)
        if 0x20 <= code <= 0x7E:
            out.append(char)
        elif code <= 0xFF:
            out.append(f"\\x{code:02x}")
        elif code <= 0xFFFF:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    text = "".join(out)
    return text if len(text) <= limit else text[: limit - 3] + "..."


class TerminalCheckpointHandler:
    """Ask a person at a terminal, and refuse unless they clearly say yes.

    The human-attached counterpart to `AutoDenyHandler`. It is deliberately
    hard to approve by accident and easy to refuse:

    - **Only `y` or `yes` approves** (any case). An empty line, `n`, anything
      else, end of input, or an error while reading refuses.
    - **No terminal means no.** When the input stream is not interactive
      (piped stdin, a CI job, a service) nothing is asked and the checkpoint
      is refused: a run nobody can answer must not skip the safeguard it
      declared. Pass `interactive=True` only for a stream you know a person is
      driving (a test, or a wrapper that relays a person's answers).
    - **Silence means no.** After `timeout_s` seconds without an answer the
      checkpoint is refused. `timeout_s=None` waits indefinitely, for an
      attended session that would rather block than refuse.
    - **A late answer is never an approval.** The read that timed out cannot
      be cancelled, so it is left running and its eventual line is thrown
      away. While it is still pending the handler refuses further checkpoints
      instead of risking reading the stale line as the answer to a new
      question.
    - **One question at a time.** Concurrent checkpoints queue on a lock;
      two prompts sharing one terminal would let an answer land on the
      wrong question.
    - **The prompt is ASCII**, and every field taken from the call is escaped
      (see `_ascii`), so the agent cannot rewrite what the person is shown.

    The reason string recorded on the chain is fixed text chosen here, never
    the person's raw input. Streams are injectable (`input_stream`,
    `output_stream`) and resolved at call time when omitted, so the handler
    follows `sys.stdin` and `sys.stdout` as they are then.
    """

    def __init__(
        self,
        *,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        timeout_s: float | None = 60.0,
        interactive: bool | None = None,
    ) -> None:
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError(f"timeout_s must be positive or None, got {timeout_s!r}")
        self._input = input_stream
        self._output = output_stream
        self._timeout_s = timeout_s
        self._interactive = interactive
        self._lock = threading.Lock()
        self._stale_read: threading.Thread | None = None

    def decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint, now_us: int
    ) -> tuple[bool, str]:
        with self._lock:
            return self._decide(agent_id=agent_id, resource=resource, checkpoint=checkpoint)

    def _decide(
        self, *, agent_id: str, resource: Resource, checkpoint: Checkpoint
    ) -> tuple[bool, str]:
        source = self._input if self._input is not None else sys.stdin
        out = self._output if self._output is not None else sys.stdout
        require = _ascii(checkpoint.require)

        if not self._is_interactive(source):
            self._say(out, f"checkpoint refused: no interactive terminal to ask ({require})")
            return False, f"no interactive terminal attached; refusing ({checkpoint.require})"

        stale = self._stale_read
        if stale is not None and stale.is_alive():
            self._say(out, "checkpoint refused: an earlier prompt timed out and is still waiting")
            return False, "an earlier checkpoint prompt timed out and its read is still pending"
        self._stale_read = None

        amount = "" if resource.amount is None else f"  amount {_ascii(resource.amount)}"
        when = ", ".join(f"{_ascii(k)} {_ascii(v)}" for k, v in sorted(checkpoint.when.items()))
        self._say(out, "")
        self._say(out, "=== CausalMesh checkpoint: approval needed ===")
        self._say(out, f"agent:     {_ascii(agent_id)}")
        self._say(out, f"resource:  {_ascii(resource.describe())}{amount}")
        self._say(out, f"rule:      on {_ascii(checkpoint.on)}, require {require}")
        if when:
            self._say(out, f"when:      {when}")
        self._say(out, "Only 'y' or 'yes' approves. Anything else, or silence, refuses.")
        self._write(out, "approve? [y/N]: ")

        answered, line = self._read_line(source)
        if not answered:
            self._say(out, "")
            self._say(out, "checkpoint refused: no answer in time")
            return False, f"no answer within {self._timeout_s:g}s; refusing ({checkpoint.require})"
        if line is None:
            self._say(out, "checkpoint refused: input closed")
            return False, "input closed before an answer; refusing"
        if line.strip().lower() in _APPROVE_ANSWERS:
            self._say(out, "checkpoint approved")
            return True, "approved by the operator at the terminal"
        self._say(out, "checkpoint refused")
        return False, "declined by the operator at the terminal"

    def _is_interactive(self, source: TextIO) -> bool:
        if self._interactive is not None:
            return self._interactive
        try:
            return bool(source.isatty())
        except (AttributeError, ValueError):
            return False

    def _read_line(self, source: TextIO) -> tuple[bool, str | None]:
        """`(answered, line)`. `line` is None on end of input or a read error."""
        if self._timeout_s is None:
            try:
                text = source.readline()
            except (OSError, ValueError):
                return True, None
            return True, (text if text else None)

        box: list[str | None] = []

        def read() -> None:
            try:
                text = source.readline()
                box.append(text if text else None)
            except (OSError, ValueError):
                box.append(None)

        reader = threading.Thread(target=read, name="causalmesh-checkpoint-read", daemon=True)
        reader.start()
        reader.join(self._timeout_s)
        if reader.is_alive():
            self._stale_read = reader
            return False, None
        return True, box[0] if box else None

    @staticmethod
    def _write(out: TextIO, text: str) -> None:
        try:
            out.write(text)
            out.flush()
        except (OSError, ValueError):
            pass

    def _say(self, out: TextIO, text: str) -> None:
        self._write(out, text + "\n")


def evaluate_checkpoints(
    checkpoints: tuple[Checkpoint, ...],
    *,
    agent_id: str,
    resource: Resource,
    handler: CheckpointHandler,
    now_us: int,
) -> CheckpointDecision | None:
    """The first checkpoint that matches this resource, decided by `handler`.

    `None` when nothing matches — a resource with no declared checkpoint is
    not gated by this rule at all, the same "declare the parts you care
    about" default `Contract` uses elsewhere.
    """
    for checkpoint in checkpoints:
        if checkpoint.on != resource.kind.value:
            continue
        if not _when_matches(checkpoint.when, resource):
            continue
        approved, reason = handler.decide(
            agent_id=agent_id, resource=resource, checkpoint=checkpoint, now_us=now_us
        )
        return CheckpointDecision(
            approved=approved, checkpoint=checkpoint, resource=resource, reason=reason
        )
    return None


def _when_matches(when: dict[str, str], resource: Resource) -> bool:
    """Every clause in `when` must match. Only `usd` (against `resource.amount`)

    is understood today.
    """
    for key, expression in when.items():
        if key != "usd":
            raise ValueError(f"unknown checkpoint `when` key: {key!r}; only 'usd' is understood")
        if not _usd_matches(expression, resource.amount):
            return False
    return True


def _usd_matches(expression: str, amount: Decimal | None) -> bool:
    match = _COMPARISON.match(expression.strip())
    if match is None:
        raise ValueError(f"checkpoint `when.usd` must look like '>0.50', got {expression!r}")
    operator, threshold_text = match.groups()
    try:
        threshold = Decimal(threshold_text)
    except InvalidOperation as exc:
        raise ValueError(
            f"checkpoint `when.usd` threshold is not a number: {threshold_text!r}"
        ) from exc
    if amount is None:
        return False
    comparisons = {
        "==": amount.__eq__,
        ">=": amount.__ge__,
        "<=": amount.__le__,
        ">": amount.__gt__,
        "<": amount.__lt__,
    }
    return bool(comparisons[operator](threshold))
