"""The run loop and the run state machine (spec §63, §79 to §81).

The scheduler owns *when* runs happen and *what state each is in*. It never
touches agent internals: it hands a task and a config to `tasks.execute_task`
and records what comes back. That boundary is an architectural invariant
(`docs/PLAN.md`), and it is what keeps the scheduler unable to influence an
outcome it is also recording.
"""

from __future__ import annotations

from .loop import ExperimentRunner, LoopReport, RunEnvironment
from .states import (
    TERMINAL_STATES,
    TRANSITIONS,
    InvalidTransitionError,
    RunState,
    can_transition,
    check_transition,
    describe,
    is_retryable,
    is_terminal,
)

__all__ = [
    "TERMINAL_STATES",
    "TRANSITIONS",
    "ExperimentRunner",
    "InvalidTransitionError",
    "LoopReport",
    "RunEnvironment",
    "RunState",
    "can_transition",
    "check_transition",
    "describe",
    "is_retryable",
    "is_terminal",
]
