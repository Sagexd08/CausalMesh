"""The logical clock that stamps the signed chain.

The chain is bit-reproducible (AGENTS.md: nothing non-reproducible in the
signed chain), and a wall-clock timestamp is exactly that: two identical
sessions would never produce the same head hash. So the timestamp an event is
signed with is a *logical* time, ``base_us + n * tick_us`` for the n-th call
of the session, and the wall-clock time of the call is recorded beside the
chain, in the unsigned envelope, where it can differ between runs without
touching the evidence.

The same value is handed to the gate and the ledger, so a verdict, a ledger
row and a signed event describe one moment and sort the same way.

What this changes, stated rather than hidden:

- Time in a session is *call count*. A lease or window measured in seconds
  lasts ``seconds * 1_000_000 / tick_us`` calls, however long those calls
  take in real time.
- A lease must be acquired on this clock (``now_us``), not on the wall
  clock, or it is stamped with a time the gate's clock never reaches.
"""

from __future__ import annotations

import threading

__all__ = ["DEFAULT_CLOCK_BASE_US", "DEFAULT_CLOCK_TICK_US", "LogicalClock"]

# A constant, so two sessions agree without being told to. Zero is read as
# "not a date" by anyone who sees it, which is the point: a value that looked
# like a real timestamp would invite being read as one.
DEFAULT_CLOCK_BASE_US = 0

# One logical second per call, so a lease of N seconds lasts N calls.
DEFAULT_CLOCK_TICK_US = 1_000_000


class LogicalClock:
    """Deterministic per-session time: ``base_us + n * tick_us``.

    ``tick()`` issues the next time. ``observe()`` takes a time the caller
    chose (``now_us=``) and moves the clock past it, so a later logical tick
    can never go backwards behind a caller-supplied one. Thread-safe, because
    two threads calling ``tick()`` must not be issued the same time.
    """

    def __init__(
        self, *, base_us: int = DEFAULT_CLOCK_BASE_US, tick_us: int = DEFAULT_CLOCK_TICK_US
    ) -> None:
        for name, value, minimum in (("base_us", base_us, 0), ("tick_us", tick_us, 1)):
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}, got {value!r}")
        self._base_us = base_us
        self._tick_us = tick_us
        self._last: int | None = None
        self._lock = threading.Lock()

    @property
    def base_us(self) -> int:
        return self._base_us

    @property
    def tick_us(self) -> int:
        return self._tick_us

    @property
    def now_us(self) -> int:
        """The most recently issued time, or ``base_us`` before the first call.

        This is the moment to acquire a lease at so that it expires on the
        clock the gate reads.
        """
        with self._lock:
            return self._base_us if self._last is None else self._last

    def tick(self) -> int:
        """Issue the time for the next call."""
        with self._lock:
            self._last = self._base_us if self._last is None else self._last + self._tick_us
            return self._last

    def observe(self, now_us: int) -> int:
        """Accept a caller-chosen time and keep later ticks strictly after it."""
        with self._lock:
            if self._last is None or now_us > self._last:
                self._last = now_us
            return now_us

    def to_dict(self) -> dict[str, int | str]:
        return {"base_us": self._base_us, "kind": "logical", "tick_us": self._tick_us}
