"""A wall-clock budget for one run, checked cooperatively (`docs/backlog.md`,
"Timeout as a distinct run state").

Two mechanisms bound a run, and they are deliberately different:

- **The cooperative check** lives here. `execute_task` asks the deadline
  whether it has expired before every turn and before every agent acts, and
  unwinds cleanly if it has. Cleanly is the point: the relay, the claim
  registry and the chain store are all closed by the code that opened them,
  and the chain written so far is returned intact.
- **The hard guard** lives in `scheduler.watchdog`. It cannot rely on the
  agent ever returning control, so it runs the whole run on a worker thread
  and gives up on it from outside.

This module is at the `tasks` layer, not in `scheduler`, because
`execute_task` has to import it and `scheduler.loop` already imports
`tasks`. Putting it in `scheduler` would close an import cycle.

**Nothing here is signed.** A deadline is wall-clock time. It is never
written into an event; the run artifact's envelope records that a limit was
hit and how long the run had been going (`scheduler.loop`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

__all__ = ["PartialRun", "RunDeadline", "RunTimedOutError"]


@dataclass(frozen=True)
class PartialRun:
    """What a run had produced when it was cut off.

    `records` is a prefix of the signed chain. A prefix of a hash chain is
    itself a valid chain, so it verifies offline like any other; what it
    lacks is the events the run never reached, and in particular the
    acceptance decision, which is only made after a run ends.

    `agent_summaries` is empty when the run was abandoned from outside: an
    agent that never returned control cannot be asked to summarise itself,
    and inventing a summary for it would be fabricating evidence.
    """

    run_id: str
    records: list[dict[str, Any]]
    head_hash: str | None
    where: str
    agent_summaries: dict[str, dict[str, Any]] = field(default_factory=dict)


class RunTimedOutError(RuntimeError):
    """A run exceeded its wall-clock budget.

    Not a failure of the agents or the harness, which is why it is its own
    type: `scheduler.loop` records it as TIMED_OUT, a different state with
    different retry semantics from FAILED.
    """

    def __init__(
        self,
        message: str,
        *,
        detected_by: str,
        partial: PartialRun | None = None,
        limit_s: float | None = None,
        elapsed_s: float | None = None,
        thread_abandoned: bool = False,
        late_result_discarded: bool = False,
    ) -> None:
        super().__init__(message)
        # How the overrun was noticed: "deadline_check" (the run saw its own
        # deadline between turns), "cancelled" (the watchdog cancelled the
        # awaiting task) or "abandoned" (the run never returned control and
        # was given up on). Wall-clock facts, kept out of the signed chain.
        self.detected_by = detected_by
        self.partial = partial
        self.limit_s = limit_s
        self.elapsed_s = elapsed_s
        # True when the run's thread was still executing agent code when the
        # watchdog gave up. Python cannot kill a thread, so this is the one
        # case where work continues after the state says TIMED_OUT.
        self.thread_abandoned = thread_abandoned
        # True when the run finished normally after its budget had already
        # been declared spent; the result is not used.
        self.late_result_discarded = late_result_discarded


class RunDeadline:
    """A wall-clock budget for one run.

    Uses a monotonic clock, so it neither jumps with the system clock nor
    depends on the run's own logical timestamps: `RunConfig.base_time_us`
    and `tick_us` are a simulated timeline, and mixing the two would make
    "how long did it take" depend on the scenario rather than the machine.
    """

    def __init__(
        self,
        limit_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(limit_s, bool) or not isinstance(limit_s, (int, float)) or limit_s <= 0:
            raise ValueError(f"a run timeout must be a positive number of seconds, got {limit_s!r}")
        self.limit_s = float(limit_s)
        self._clock = clock
        self._started = clock()
        self._tripped = threading.Event()
        self._snapshot: Callable[[], list[dict[str, Any]]] | None = None
        self._head: Callable[[], str | None] | None = None

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._started

    @property
    def expired(self) -> bool:
        return self._tripped.is_set() or self.elapsed_s >= self.limit_s

    def trip(self) -> None:
        """Mark the deadline expired now, from any thread.

        Called by the watchdog when it gives up waiting, so a run that is
        merely slow (rather than hung) notices at its next check and unwinds
        on its own.
        """
        self._tripped.set()

    def check(self, where: str) -> None:
        """Raise `RunTimedOutError` if the budget is spent."""
        if self.expired:
            raise RunTimedOutError(
                f"run exceeded its {self.limit_s:g}s wall-clock limit ({where})",
                detected_by="deadline_check",
            )

    def bind_chain(
        self,
        snapshot: Callable[[], list[dict[str, Any]]],
        head: Callable[[], str | None],
    ) -> None:
        """Let an outside observer read the chain written so far.

        The watchdog uses this when it has to abandon a run that never
        returned control: the run cannot hand back its evidence, but the
        relay is a thread-safe object and its records can still be read.
        """
        self._snapshot = snapshot
        self._head = head

    def chain_snapshot(self) -> tuple[list[dict[str, Any]], str | None] | None:
        """The chain so far, or None if the run never bound one.

        None is not an empty chain: a run that died before assembling its
        relay produced no chain to speak of, and the caller records that as
        unknown rather than as zero events.
        """
        if self._snapshot is None or self._head is None:
            return None
        return self._snapshot(), self._head()
