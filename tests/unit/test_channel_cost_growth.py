"""Coordination-cost growth laws, measured (spec §15, §18, §45, §46).

§46 gives analytical cost models. This module pins the *observed* growth of
the implemented channels against closed forms, so a change that quietly
altered a channel's asymptotics — adding truncation to C1, or making C2's
window grow — would fail here rather than silently flattening the curve the
experiment exists to measure.

A distinction worth stating, because conflating the two would put a wrong
prediction into the analysis module:

    §46's C_tr(T) = mu * T(T-1)/2 counts pairwise exchanges among T AGENTS.

    What this module measures is cumulative injected cost over T TURNS with
    one new message per turn. Turn t replays t+1 messages, because the newly
    arrived event is part of that turn's history, so the closed form is
    mu * T(T+1)/2.

Both are quadratic and both express C1's defining property. They are not the
same quantity, and the analysis module must not substitute one for the other.
"""

from __future__ import annotations

import pytest

from causalmesh.channels import MetadataChannel, NullChannel, Room, TranscriptChannel
from causalmesh.events.schema import Event, EventIdentity, EventType

pytestmark = pytest.mark.unit

BASE_TIME = 1_700_000_000_000_000
WINDOW = 8


def make_event(sequence: int) -> Event:
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=EventIdentity(
            experiment_id="exp_cost",
            task_id="task_cost",
            run_id="run_001",
            agent_id="agent_a",
            arm="C2",
        ),
        event_type=EventType.WRITE,
        sequence=sequence,
        timestamp_us=BASE_TIME + sequence,
        paths=("src/schema.py",),
    )


def transcript_tokens(turns: int) -> int:
    channel = TranscriptChannel("agent_b", Room("run_001", "task_cost"))
    for turn in range(turns):
        channel.offer((make_event(turn),), turn=turn)
    return channel.accounting.total_tokens


def metadata_tokens(turns: int, *, window: int = WINDOW) -> int:
    channel = MetadataChannel("agent_b", window=window)
    for turn in range(turns):
        channel.offer((make_event(turn),), turn=turn)
    return channel.accounting.total_tokens


class TestTranscriptGrowth:
    """C1 is quadratic, exactly."""

    def test_cost_follows_the_closed_form_with_one_constant(self) -> None:
        """A single fitted mu must predict every T, not just the one it came from.

        Refitting the constant per data point would make almost any curve
        look like a match, so mu is fitted once at T=60 and then checked
        against every smaller T.
        """
        mu = transcript_tokens(60) / (60 * 61 / 2)
        for turns in (1, 2, 5, 10, 20, 40, 60):
            predicted = mu * turns * (turns + 1) / 2
            assert transcript_tokens(turns) == pytest.approx(predicted, rel=0.01)

    def test_the_per_message_constant_is_stable(self) -> None:
        # mu is the token cost of one rendered message; it must not depend on
        # how many turns have elapsed.
        constants = [transcript_tokens(t) / (t * (t + 1) / 2) for t in (10, 30, 60)]
        assert max(constants) == pytest.approx(min(constants), rel=0.01)

    def test_doubling_the_turns_roughly_quadruples_the_cost(self) -> None:
        # The signature of quadratic growth, stated in a form that does not
        # depend on the exact closed form being right.
        assert transcript_tokens(40) == pytest.approx(4 * transcript_tokens(20), rel=0.1)

    def test_growth_is_not_linear(self) -> None:
        # Guards against a future "optimisation" that truncated the history:
        # §15 forbids silent truncation precisely because it would do this.
        assert transcript_tokens(40) > 3 * transcript_tokens(20)


class TestMetadataGrowth:
    """C2 is linear, bounded by the window."""

    def test_doubling_the_turns_roughly_doubles_the_cost(self) -> None:
        assert metadata_tokens(40) == pytest.approx(2 * metadata_tokens(20), rel=0.1)

    def test_cost_stays_within_the_window_bound(self) -> None:
        """§46: C_md(T) <= nu * w * T."""
        # nu is the cost of one filled window slot, fitted from a run where
        # every turn injects exactly one event.
        nu = metadata_tokens(60) / (WINDOW * 60)
        for turns in (10, 30, 60):
            assert metadata_tokens(turns) <= nu * WINDOW * turns * 1.01

    def test_a_wider_window_costs_no_less(self) -> None:
        # Monotonic in w: a wider window can only admit more.
        assert metadata_tokens(20, window=16) >= metadata_tokens(20, window=4)

    def test_the_window_caps_cost_under_a_flood(self) -> None:
        # Twenty events per turn, window of 4: cost must track the window,
        # not the arrival rate. This is what makes C2 linear.
        channel = MetadataChannel("agent_b", window=4)
        for turn in range(10):
            channel.offer(tuple(make_event(turn * 20 + i) for i in range(20)), turn=turn)
        assert channel.accounting.events_injected == 40
        assert channel.accounting.events_dropped > 0


class TestCrossover:
    def test_the_transcript_starts_cheaper_and_ends_dearer(self) -> None:
        """§46's T*: below it the transcript wins, above it the window does.

        Worth pinning because it is a genuinely counter-intuitive result —
        the structured rendering is *larger per event*, so C2 loses on short
        runs and only wins through bounded replay.
        """
        assert transcript_tokens(1) < metadata_tokens(1)
        assert transcript_tokens(30) > metadata_tokens(30)

    def test_a_crossover_turn_exists_and_is_small(self) -> None:
        crossover = next(
            turns for turns in range(1, 100) if transcript_tokens(turns) > metadata_tokens(turns)
        )
        assert 1 < crossover < 20


class TestNullCost:
    def test_c0_costs_nothing_at_any_length(self) -> None:
        for turns in (1, 10, 60):
            channel = NullChannel("agent_b")
            for turn in range(turns):
                channel.offer((), turn=turn)
            assert channel.accounting.total_tokens == 0
            assert channel.accounting.total_bytes == 0
