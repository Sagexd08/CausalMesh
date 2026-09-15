"""The run state machine (spec §63, §81).

A run moves through a fixed set of states, and the legal transitions are
declared as data:

    PLANNED ─→ RUNNING ─→ COMPLETED
                  │  ├───→ FAILED
                  │  ├───→ TIMED_OUT
                  │  └───→ ABANDONED
                  └─→ (crash) ─→ ABANDONED ─→ RUNNING   (resume)

Why a machine rather than a boolean. §81 requires a failed run to produce
full evidence, which means "failed" must be a recorded destination, not the
absence of a record. And a run that was interrupted must be distinguishable
from one that failed on its own terms: the first can be legitimately
re-executed, the second is a result. Collapsing them would let a resume
quietly re-run failures until they passed, which is selection on the outcome
— the most damaging thing a scheduler could do to an experiment.

**COMPLETED does not mean the task succeeded.** It means the run reached
its end and produced a verdict. A run whose agents failed the task is
COMPLETED with `succeeded=False`. Conflating execution status with task
outcome would make the primary outcome unmeasurable, because failed tasks
would be missing from the denominator.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "TERMINAL_STATES",
    "TRANSITIONS",
    "InvalidTransitionError",
    "RunState",
    "can_transition",
    "check_transition",
    "is_retryable",
    "is_terminal",
]


class RunState:
    """The states a run can occupy.

    Plain string constants rather than an enum: these are persisted to
    SQLite and written into manifests, and a string that round-trips
    through storage as itself is easier to verify by eye in a database than
    an enum's `.value`. The transition table below is what actually
    constrains them.
    """

    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABANDONED = "abandoned"

    ALL = frozenset({PLANNED, RUNNING, COMPLETED, FAILED, TIMED_OUT, ABANDONED})


# A run that reached one of these is finished and will not be re-executed
# by a resume. ABANDONED is deliberately *not* terminal: it is the state an
# interrupted run is left in, and resuming it is the whole point.
TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.TIMED_OUT})


TRANSITIONS: dict[str, frozenset[str]] = {
    RunState.PLANNED: frozenset({RunState.RUNNING, RunState.ABANDONED}),
    RunState.RUNNING: frozenset(
        {
            RunState.COMPLETED,
            RunState.FAILED,
            RunState.TIMED_OUT,
            RunState.ABANDONED,
        }
    ),
    # Terminal. A completed run is evidence; moving it anywhere else would
    # mean rewriting a result, which §31 forbids for raw data and this
    # forbids for the run's status.
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.TIMED_OUT: frozenset(),
    # The only recoverable state: an interrupted run may be started again.
    RunState.ABANDONED: frozenset({RunState.RUNNING}),
}


class InvalidTransitionError(RuntimeError):
    """Raised when a run is moved between states the machine forbids."""


def can_transition(source: str, destination: str) -> bool:
    if source not in RunState.ALL:
        return False
    return destination in TRANSITIONS[source]


def check_transition(source: str, destination: str) -> None:
    """Assert a transition is legal, raising with the reason if not.

    Used by the store on every write. A scheduler bug that tried to move a
    COMPLETED run back to RUNNING would otherwise silently re-execute a run
    that already has a result, producing two results for one planned unit
    of work and an inflated, duplicated denominator.
    """
    if source not in RunState.ALL:
        raise InvalidTransitionError(f"unknown source state {source!r}")
    if destination not in RunState.ALL:
        raise InvalidTransitionError(f"unknown destination state {destination!r}")
    if destination not in TRANSITIONS[source]:
        allowed = sorted(TRANSITIONS[source])
        raise InvalidTransitionError(
            f"cannot move a run from {source!r} to {destination!r}; "
            f"legal destinations are {allowed or '(none: terminal)'}"
        )


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def is_retryable(state: str) -> bool:
    """Whether a resume may execute this run again.

    Only PLANNED (never started) and ABANDONED (interrupted before it could
    record a verdict) qualify. FAILED and TIMED_OUT are results and are left
    alone: re-running them until they pass would select on the outcome.
    """
    return state in (RunState.PLANNED, RunState.ABANDONED)


def describe(state: str) -> dict[str, Any]:
    return {
        "retryable": is_retryable(state),
        "state": state,
        "terminal": is_terminal(state),
        "transitions": sorted(TRANSITIONS.get(state, frozenset())),
    }
