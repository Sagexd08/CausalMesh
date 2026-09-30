"""The run state machine (spec §63, §81).

A run moves through a fixed set of states, and the legal transitions are
declared as data:

    PLANNED ─→ RUNNING ─→ COMPLETED
                  │  ├───→ FAILED
                  │  ├───→ TIMED_OUT
                  │  ├───→ ABANDONED
                  │  └───→ HANDED_OFF ─→ RUNNING      (continues under another agent)
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

**TIMED_OUT is assigned by a whole-run watchdog** (`ExperimentRunner`'s
`run_timeout_s`, off by default). It is a result, like FAILED: a run that
ran out of wall-clock budget is never retried.

**HANDED_OFF is a prerequisite, not a capability.** It names the state of a
run whose first agent has stopped and whose continuation under a different
agent has not yet started. Nothing in the loop assigns it yet: there is no
`recover` decision and no second agent (see `docs/backlog.md`, "Agent
handoff package on recovery"). It is additive: states are persisted as plain
strings, so no stored row changes meaning.
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
    HANDED_OFF = "handed_off"

    ALL = frozenset({PLANNED, RUNNING, COMPLETED, FAILED, TIMED_OUT, ABANDONED, HANDED_OFF})


TERMINAL_STATES = frozenset({RunState.COMPLETED, RunState.FAILED, RunState.TIMED_OUT})


TRANSITIONS: dict[str, frozenset[str]] = {
    RunState.PLANNED: frozenset({RunState.RUNNING, RunState.ABANDONED}),
    RunState.RUNNING: frozenset(
        {
            RunState.COMPLETED,
            RunState.FAILED,
            RunState.TIMED_OUT,
            RunState.ABANDONED,
            RunState.HANDED_OFF,
        }
    ),
    RunState.COMPLETED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.TIMED_OUT: frozenset(),
    RunState.ABANDONED: frozenset({RunState.RUNNING}),
    # Not terminal and not retryable. The only ways out are the continuation
    # (RUNNING, under the agent the package names) or ABANDONED, which is how
    # a run whose process died while it waited for its next agent is unstuck.
    RunState.HANDED_OFF: frozenset({RunState.RUNNING, RunState.ABANDONED}),
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
    HANDED_OFF is not retryable either: it is waiting for a *continuation*
    carrying the first agent's work, and a cold re-run would discard it.
    """
    return state in (RunState.PLANNED, RunState.ABANDONED)


def describe(state: str) -> dict[str, Any]:
    return {
        "retryable": is_retryable(state),
        "state": state,
        "terminal": is_terminal(state),
        "transitions": sorted(TRANSITIONS.get(state, frozenset())),
    }
