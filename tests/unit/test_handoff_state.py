"""The HANDED_OFF run state: "run continues under a different agent".

Additive and unused by the loop. These tests pin what the state may do so
that nothing comes to depend on a shape the machine does not declare, and
that the index (which persists it as a plain string) handles it like every
other state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.experiments import plan_experiment, profile
from causalmesh.scheduler import (
    TERMINAL_STATES,
    InvalidTransitionError,
    RunState,
    can_transition,
    check_transition,
    is_retryable,
    is_terminal,
)
from causalmesh.storage import RunIndex

pytestmark = pytest.mark.unit

SEED = b"causalmesh-handoff-state-seed-01"


@pytest.fixture
def plan():
    return plan_experiment(
        experiment_id="exp",
        profile=profile("pilot"),
        task_ids=["t1"],
        master_seed=SEED,
    )


@pytest.fixture
def index(tmp_path: Path):
    with RunIndex(tmp_path / "index.db") as opened:
        yield opened


class TestStateMachine:
    def test_a_running_run_may_be_handed_off(self) -> None:
        check_transition(RunState.RUNNING, RunState.HANDED_OFF)

    def test_a_handed_off_run_may_continue(self) -> None:
        check_transition(RunState.HANDED_OFF, RunState.RUNNING)

    def test_a_handed_off_run_may_be_abandoned(self) -> None:
        # How a run whose process died while waiting for its next agent is
        # unstuck.
        check_transition(RunState.HANDED_OFF, RunState.ABANDONED)

    def test_a_handed_off_run_cannot_be_given_a_verdict_without_continuing(self) -> None:
        for destination in (RunState.COMPLETED, RunState.FAILED, RunState.TIMED_OUT):
            with pytest.raises(InvalidTransitionError):
                check_transition(RunState.HANDED_OFF, destination)

    def test_a_run_cannot_be_handed_off_before_it_has_started(self) -> None:
        with pytest.raises(InvalidTransitionError):
            check_transition(RunState.PLANNED, RunState.HANDED_OFF)

    def test_a_terminal_run_cannot_be_handed_off(self) -> None:
        for state in TERMINAL_STATES:
            assert not can_transition(state, RunState.HANDED_OFF)

    def test_it_is_not_terminal_and_not_retryable(self) -> None:
        # Retrying would re-run cold and discard the work being handed over.
        assert not is_terminal(RunState.HANDED_OFF)
        assert not is_retryable(RunState.HANDED_OFF)

    def test_the_persisted_spelling_is_stable(self) -> None:
        # States are stored as plain strings; a rename would orphan rows.
        assert RunState.HANDED_OFF == "handed_off"

    def test_the_existing_spellings_did_not_move(self) -> None:
        assert sorted(RunState.ALL - {RunState.HANDED_OFF}) == [
            "abandoned",
            "completed",
            "failed",
            "planned",
            "running",
            "timed_out",
        ]


class TestIndex:
    def test_a_running_run_can_be_handed_off_and_continued(self, index: RunIndex, plan) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        handed = index.hand_off(record.run_id, now_us=3)
        assert handed.state == RunState.HANDED_OFF
        continued = index.continue_handed_off(record.run_id, now_us=4)
        assert continued.state == RunState.RUNNING
        # A continuation is not another attempt at the run.
        assert continued.attempts == 1

    def test_the_handoff_is_visible_in_the_transition_log(self, index: RunIndex, plan) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        index.hand_off(record.run_id, now_us=3)
        index.continue_handed_off(record.run_id, now_us=4)
        states = [t["to_state"] for t in index.transitions(record.run_id)]
        assert states == [
            RunState.PLANNED,
            RunState.RUNNING,
            RunState.HANDED_OFF,
            RunState.RUNNING,
        ]

    def test_a_planned_run_cannot_be_handed_off(self, index: RunIndex, plan) -> None:
        index.register_plan(plan, now_us=1)
        with pytest.raises(InvalidTransitionError):
            index.hand_off(plan.runs[0].run_id, now_us=2)

    def test_a_finished_run_cannot_be_handed_off(self, index: RunIndex, plan) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        index.finish(record.run_id, state=RunState.COMPLETED, now_us=3, succeeded=True)
        with pytest.raises(InvalidTransitionError):
            index.hand_off(record.run_id, now_us=4)

    def test_an_unknown_run_is_a_key_error(self, index: RunIndex) -> None:
        with pytest.raises(KeyError):
            index.hand_off("nope", now_us=1)

    def test_a_handed_off_run_is_not_claimed_by_the_loop(self, index: RunIndex, plan) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        index.hand_off(record.run_id, now_us=3)
        claimed_ids = set()
        while (claimed := index.claim_next("exp", now_us=10)) is not None:
            claimed_ids.add(claimed.run_id)
        assert record.run_id not in claimed_ids
        assert index.get(record.run_id).state == RunState.HANDED_OFF

    def test_a_handed_off_run_is_not_complete(self, index: RunIndex, plan) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        index.hand_off(record.run_id, now_us=3)
        assert not index.is_complete("exp")
        assert index.counts("exp")[RunState.HANDED_OFF] == 1

    @pytest.mark.failure
    def test_a_run_found_handed_off_at_startup_is_abandoned_not_stranded(
        self, index: RunIndex, plan
    ) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        index.hand_off(record.run_id, now_us=3)
        assert index.abandon_running("exp", now_us=4) == 1
        assert index.get(record.run_id).state == RunState.ABANDONED
        last = index.transitions(record.run_id)[-1]
        assert last["from_state"] == RunState.HANDED_OFF
        assert "handed off" in last["note"]

    @pytest.mark.failure
    def test_abandoning_running_runs_still_records_running_as_the_source(
        self, index: RunIndex, plan
    ) -> None:
        index.register_plan(plan, now_us=1)
        record = index.claim_next("exp", now_us=2)
        index.abandon_running("exp", now_us=3)
        assert index.transitions(record.run_id)[-1]["from_state"] == RunState.RUNNING

    def test_a_database_written_before_the_state_existed_still_reads(
        self, tmp_path: Path, plan
    ) -> None:
        """No migration: `state` is free text, so the addition is additive."""
        path = tmp_path / "old.db"
        with RunIndex(path) as first:
            first.register_plan(plan, now_us=1)
            first.claim_next("exp", now_us=2)
        with RunIndex(path) as reopened:
            counts = reopened.counts("exp")
            assert counts[RunState.HANDED_OFF] == 0
            assert counts[RunState.RUNNING] == 1
