"""Unit tests for the run state machine (spec §63, §81).

The machine's job is to make two mistakes impossible: re-executing a run
that already has a result, and losing a run that was interrupted. Both are
silent in a system without one, so these tests attack the transitions
directly rather than exercising them through the loop.
"""

from __future__ import annotations

import pytest

from causalmesh.scheduler import (
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

pytestmark = pytest.mark.unit


class TestStructure:
    def test_every_state_has_a_transition_entry(self) -> None:
        # A state missing from the table would raise KeyError on the first
        # run that reached it, mid-collection.
        assert set(TRANSITIONS) == RunState.ALL

    def test_every_destination_is_a_real_state(self) -> None:
        for source, destinations in TRANSITIONS.items():
            for destination in destinations:
                assert destination in RunState.ALL, f"{source} -> {destination}"

    def test_every_state_is_reachable_from_planned(self) -> None:
        """No orphan states.

        A state nothing can reach is dead code (§92) — or worse, a state
        the scheduler believes it can write and the machine will reject.
        """
        seen = {RunState.PLANNED}
        frontier = [RunState.PLANNED]
        while frontier:
            for destination in TRANSITIONS[frontier.pop()]:
                if destination not in seen:
                    seen.add(destination)
                    frontier.append(destination)
        assert seen == RunState.ALL


class TestTerminality:
    def test_the_terminal_states_are_the_ones_with_a_verdict(self) -> None:
        # Written as a sorted comparison rather than a set literal: ruff
        # reads `CONSTANT == {...}` as a Yoda condition, and inverting the
        # assertion to satisfy it would put the expectation on the left,
        # which reads worse than this.
        assert sorted(TERMINAL_STATES) == ["completed", "failed", "timed_out"]

    def test_a_terminal_state_has_no_way_out(self) -> None:
        for state in TERMINAL_STATES:
            assert TRANSITIONS[state] == frozenset()

    def test_abandoned_is_not_terminal(self) -> None:
        """The distinction resume depends on.

        An interrupted run has no verdict, so re-executing it is not
        selection on the outcome — unlike re-executing a FAILED run.
        """
        assert not is_terminal(RunState.ABANDONED)
        assert is_retryable(RunState.ABANDONED)

    def test_a_failed_run_is_never_retried(self) -> None:
        # Retrying failures until they pass would select on the outcome,
        # which is the most damaging thing a scheduler can do to an
        # experiment. §81: a failed run is evidence.
        assert not is_retryable(RunState.FAILED)
        assert not is_retryable(RunState.TIMED_OUT)
        assert not is_retryable(RunState.COMPLETED)

    def test_only_planned_and_abandoned_are_retryable(self) -> None:
        retryable = {s for s in RunState.ALL if is_retryable(s)}
        assert retryable == {RunState.PLANNED, RunState.ABANDONED}


class TestTransitions:
    def test_the_happy_path_is_legal(self) -> None:
        assert can_transition(RunState.PLANNED, RunState.RUNNING)
        assert can_transition(RunState.RUNNING, RunState.COMPLETED)

    def test_a_completed_run_cannot_restart(self) -> None:
        """The invariant that prevents a duplicated result.

        Without it, a scheduler bug would re-execute a run that already has
        a result, producing two results for one planned unit of work and an
        inflated denominator.
        """
        assert not can_transition(RunState.COMPLETED, RunState.RUNNING)
        with pytest.raises(InvalidTransitionError, match="terminal"):
            check_transition(RunState.COMPLETED, RunState.RUNNING)

    def test_a_failed_run_cannot_be_relabelled_completed(self) -> None:
        with pytest.raises(InvalidTransitionError):
            check_transition(RunState.FAILED, RunState.COMPLETED)

    def test_an_abandoned_run_may_resume(self) -> None:
        check_transition(RunState.ABANDONED, RunState.RUNNING)

    def test_an_abandoned_run_cannot_jump_straight_to_completed(self) -> None:
        # It must be executed again to earn a verdict; recording one
        # without running would fabricate a result.
        with pytest.raises(InvalidTransitionError):
            check_transition(RunState.ABANDONED, RunState.COMPLETED)

    def test_a_planned_run_cannot_skip_execution(self) -> None:
        with pytest.raises(InvalidTransitionError):
            check_transition(RunState.PLANNED, RunState.COMPLETED)

    def test_an_unknown_state_is_rejected_at_both_ends(self) -> None:
        with pytest.raises(InvalidTransitionError, match="unknown source"):
            check_transition("vibing", RunState.RUNNING)
        with pytest.raises(InvalidTransitionError, match="unknown destination"):
            check_transition(RunState.RUNNING, "vibing")

    def test_can_transition_is_false_for_unknown_states(self) -> None:
        assert not can_transition("vibing", RunState.RUNNING)

    def test_the_error_names_the_legal_destinations(self) -> None:
        # An operator reading this in a traceback needs to know what was
        # allowed, not only that something was not.
        with pytest.raises(InvalidTransitionError) as info:
            check_transition(RunState.PLANNED, RunState.COMPLETED)
        assert "running" in str(info.value)


class TestDescribe:
    def test_it_reports_the_three_facts_a_status_display_needs(self) -> None:
        described = describe(RunState.ABANDONED)
        assert described == {
            "retryable": True,
            "state": RunState.ABANDONED,
            "terminal": False,
            "transitions": [RunState.RUNNING],
        }


class TestHandedOff:
    """The transition for "this run continues under a different agent".

    HANDED_OFF is a step inside a run, not an outcome. Every property here
    exists to stop it being mistaken for one: picked up as unstarted work,
    counted as a verdict, or skipped straight to COMPLETED.
    """

    def test_a_running_run_can_be_handed_off_and_resume(self) -> None:
        check_transition(RunState.RUNNING, RunState.HANDED_OFF)
        check_transition(RunState.HANDED_OFF, RunState.RUNNING)

    def test_a_run_that_never_started_cannot_be_handed_off(self) -> None:
        with pytest.raises(InvalidTransitionError):
            check_transition(RunState.PLANNED, RunState.HANDED_OFF)

    def test_a_handoff_cannot_complete_the_run_by_itself(self) -> None:
        # The successor has to take over (back to RUNNING) and produce the
        # verdict; a run whose only recorded work is a handoff has no result.
        with pytest.raises(InvalidTransitionError):
            check_transition(RunState.HANDED_OFF, RunState.COMPLETED)

    def test_it_is_neither_terminal_nor_retryable(self) -> None:
        # Retryable would let claim_next re-execute a run that is mid-flight.
        assert not is_terminal(RunState.HANDED_OFF)
        assert not is_retryable(RunState.HANDED_OFF)

    def test_a_crash_during_a_handoff_leaves_a_way_out(self) -> None:
        # Otherwise a process that died between relieving one agent and
        # installing the next would strand the run forever.
        assert can_transition(RunState.HANDED_OFF, RunState.ABANDONED)

    def test_a_handoff_cannot_be_used_to_leave_a_terminal_state(self) -> None:
        for state in TERMINAL_STATES:
            assert not can_transition(state, RunState.HANDED_OFF)


class TestTimedOut:
    def test_a_timeout_is_a_result_and_never_retried(self) -> None:
        """The property the whole-run watchdog depends on.

        "Ran out of time" is exactly the outcome a second, luckier attempt
        would erase, so the machine must refuse to run it again.
        """
        assert is_terminal(RunState.TIMED_OUT)
        assert not is_retryable(RunState.TIMED_OUT)
        assert TRANSITIONS[RunState.TIMED_OUT] == frozenset()

    def test_a_timeout_is_reachable_from_running(self) -> None:
        check_transition(RunState.RUNNING, RunState.TIMED_OUT)
