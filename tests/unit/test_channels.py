"""Coordination channels (spec §14, §15, §16, §18).

This is layer L3 of the isolation model, and the module that makes §96's
first question answerable by arithmetic:

    Can we prove C0 received no coordination information?

The three channels are tested for the properties that make the contrasts
mean what they claim:

- C0 rejects everything **and reports a provable zero**;
- C1 grows without bound and is never silently truncated;
- C2 is bounded by `w`, and availability stays distinguishable from
  injection.
"""

from __future__ import annotations

import pytest

from causalmesh.channels import (
    DEFAULT_WINDOW,
    ChannelError,
    MetadataChannel,
    NullChannel,
    Room,
    TranscriptChannel,
    estimate_tokens,
)
from causalmesh.events.schema import Event, EventIdentity, EventType
from causalmesh.relevance import AgentInterests

pytestmark = pytest.mark.unit

RUN = "run_001"
BASE_TIME = 1_700_000_000_000_000


def make_event(
    sequence: int,
    *,
    actor: str = "agent_a",
    event_type: EventType = EventType.WRITE,
    paths: tuple[str, ...] = ("src/schema.py",),
) -> Event:
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=EventIdentity(
            experiment_id="exp_ch",
            task_id="task_ch",
            run_id=RUN,
            agent_id=actor,
            arm="C2",
        ),
        event_type=event_type,
        sequence=sequence,
        timestamp_us=BASE_TIME + sequence,
        paths=paths,
    )


class TestNullChannel:
    """§14: C0 must actively reject coordination, not merely lack it."""

    def test_an_empty_turn_is_recorded_as_zero(self) -> None:
        channel = NullChannel("agent_b")
        injection = channel.offer((), turn=0)
        assert injection.text == ""
        assert injection.bytes_injected == 0
        assert injection.events_available == 0
        assert injection.events_injected == 0

    def test_offered_events_raise_rather_than_being_ignored(self) -> None:
        """Silently dropping them would hide a contaminated run.

        Being handed events means the relay's NullDelivery was bypassed, so
        the isolation is already broken upstream. Continuing would produce a
        run that looked valid while being silently contaminated.
        """
        channel = NullChannel("agent_b")
        with pytest.raises(ChannelError, match="must receive none"):
            channel.offer((make_event(0),), turn=0)

    def test_the_error_names_the_agent_and_turn(self) -> None:
        channel = NullChannel("agent_b")
        with pytest.raises(ChannelError) as caught:
            channel.offer((make_event(0),), turn=7)
        assert "agent_b" in str(caught.value)
        assert "turn 7" in str(caught.value)

    def test_accounting_proves_no_coordination_was_received(self) -> None:
        # The §96 claim, as a checkable property rather than an inference.
        channel = NullChannel("agent_b")
        for turn in range(5):
            channel.offer((), turn=turn)

        accounting = channel.accounting
        assert accounting.received_no_coordination
        assert accounting.total_bytes == 0
        assert accounting.total_tokens == 0
        assert accounting.events_available == 0
        assert accounting.turns == 5

    def test_every_turn_leaves_a_digest(self) -> None:
        # A positive audit trail — "these are the bytes that entered" — not
        # an empty record that proves nothing.
        channel = NullChannel("agent_b")
        for turn in range(3):
            channel.offer((), turn=turn)
        digests = channel.accounting.digests
        assert len(digests) == 3
        # SHA-256 of the empty string.
        assert set(digests) == {
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        }

    def test_the_arm_is_reported(self) -> None:
        assert NullChannel("agent_b").arm == "C0"


class TestTranscriptChannel:
    """§15: unbounded, and never silently truncated."""

    def test_a_peer_event_becomes_a_message(self) -> None:
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_b", room)
        injection = channel.offer((make_event(0),), turn=0)
        assert "agent_a" in injection.text
        assert "src/schema.py" in injection.text

    def test_an_agent_does_not_see_its_own_messages(self) -> None:
        # Re-reading its own words is not coordination and would inflate cost.
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_a", room)
        injection = channel.offer((make_event(0, actor="agent_a"),), turn=0)
        assert injection.text == ""

    def test_the_history_is_replayed_in_full_every_turn(self) -> None:
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_b", room)
        for turn in range(3):
            injection = channel.offer((make_event(turn),), turn=turn)
        assert injection.events_injected == 3
        assert injection.text.count("agent_a") == 3

    def test_context_grows_monotonically(self) -> None:
        """The quadratic growth C1 exists to measure (§46)."""
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_b", room)
        sizes = []
        for turn in range(6):
            sizes.append(channel.offer((make_event(turn),), turn=turn).bytes_injected)
        assert sizes == sorted(sizes)
        assert sizes[-1] > sizes[0]

    def test_cumulative_cost_grows_faster_than_linearly(self) -> None:
        # Each turn replays everything before it, so total injected bytes
        # accumulate as roughly T(T-1)/2 rather than T.
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_b", room)
        for turn in range(10):
            channel.offer((make_event(turn),), turn=turn)
        per_turn_average = channel.accounting.total_bytes / 10
        first_turn = len("[agent_a] I wrote to src/schema.py.")
        assert per_turn_average > 2 * first_turn

    def test_nothing_is_truncated(self) -> None:
        # §15 forbids silent truncation; any limit must be configuration.
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_b", room)
        for turn in range(50):
            channel.offer((make_event(turn),), turn=turn)
        assert channel.offer((), turn=50).events_injected == 50

    def test_the_room_records_participants(self) -> None:
        room = Room(RUN, "task_ch")
        channel = TranscriptChannel("agent_c", room)
        channel.offer((make_event(0, actor="agent_a"), make_event(1, actor="agent_b")), turn=0)
        assert room.participants() == ("agent_a", "agent_b")

    def test_the_room_exports_full_messages(self) -> None:
        room = Room(RUN, "task_ch")
        TranscriptChannel("agent_b", room).offer((make_event(0),), turn=0)
        exported = room.export()
        assert len(exported) == 1
        assert set(exported[0]) == {
            "actor",
            "content",
            "event_id",
            "run_id",
            "task_id",
            "timestamp_us",
        }

    def test_the_arm_is_reported(self) -> None:
        assert TranscriptChannel("agent_b", Room(RUN, "t")).arm == "C1"


class TestMetadataChannel:
    """§16, §18: bounded, typed, and honest about what it dropped."""

    def test_the_window_bounds_what_is_injected(self) -> None:
        channel = MetadataChannel("agent_b", window=3)
        injection = channel.offer(tuple(make_event(i) for i in range(10)), turn=0)
        assert injection.events_injected == 3
        assert injection.events_available == 10
        assert injection.events_dropped == 7

    def test_the_default_window_is_eight(self) -> None:
        assert DEFAULT_WINDOW == 8
        channel = MetadataChannel("agent_b")
        assert channel.offer(tuple(make_event(i) for i in range(20)), turn=0).events_injected == 8

    def test_availability_and_injection_are_distinguishable(self) -> None:
        """§18's core requirement.

        "Never told" and "told but the window cut it" support different
        conclusions about why an arm underperformed.
        """
        channel = MetadataChannel("agent_b", window=2)
        injection = channel.offer(tuple(make_event(i) for i in range(5)), turn=0)
        assert injection.events_available == 5
        assert injection.events_injected == 2
        assert injection.events_dropped == 3
        assert injection.events_available != injection.events_injected

    def test_dropped_events_stay_pending_for_a_later_turn(self) -> None:
        # Discarding them permanently would be silent information loss; a
        # dropped event may be the most relevant one next turn.
        channel = MetadataChannel("agent_b", window=2)
        channel.offer(tuple(make_event(i) for i in range(5)), turn=0)
        assert channel.pending_count == 3
        assert channel.offer((), turn=1).events_injected == 2

    def test_every_injected_event_records_why(self) -> None:
        # §17: the selection must be explainable.
        channel = MetadataChannel(
            "agent_b",
            window=2,
            interests=AgentInterests(
                agent_id="agent_b", owned_paths=frozenset({"src/api.py"})
            ),
        )
        injection = channel.offer(
            (make_event(0, paths=("src/api.py",)), make_event(1, paths=("other.py",))),
            turn=0,
        )
        assert len(injection.selection_reasons) == 2
        assert all("reason" in r and "total" in r for r in injection.selection_reasons)

    def test_the_rendering_is_structured_not_prose(self) -> None:
        # §16: the structured channel describes what changed, not conversation.
        channel = MetadataChannel("agent_b", window=1)
        text = channel.offer((make_event(0),), turn=0).text
        assert "seq=" in text and "actor=" in text and "type=WRITE" in text
        assert "I wrote" not in text

    def test_a_single_metadata_event_is_not_smaller_than_prose(self) -> None:
        """Recorded because it is counterexample to an intuitive assumption.

        The structured rendering is *larger* per event than the prose one
        (`seq=… actor=… type=… paths=…` versus "I wrote to src/schema.py").
        C2's advantage is not compactness — it is that C1 replays the entire
        history every turn while C2 injects at most `w`.

        Asserting the wrong mechanism here would let a change that destroyed
        the real advantage pass, so the mechanism is pinned explicitly.
        """
        event = (make_event(0),)
        transcript = TranscriptChannel("agent_b", Room(RUN, "task_ch"))
        metadata = MetadataChannel("agent_b", window=8)

        assert (
            metadata.offer(event, turn=0).bytes_injected
            >= transcript.offer(event, turn=0).bytes_injected
        )

    def test_transcript_cost_overtakes_metadata_as_turns_accumulate(self) -> None:
        """The real C1→C2 contrast: quadratic versus linear growth (§46).

        C1 replays everything each turn, so cumulative cost grows as roughly
        T(T-1)/2; C2 is bounded by w per turn, so it grows as wT. C1 starts
        cheaper per turn and ends far more expensive.
        """

        def cumulative_bytes(turns: int) -> tuple[int, int]:
            transcript = TranscriptChannel("agent_b", Room(RUN, "task_ch"))
            metadata = MetadataChannel("agent_b", window=8)
            for turn in range(turns):
                event = (make_event(turn),)
                transcript.offer(event, turn=turn)
                metadata.offer(event, turn=turn)
            return transcript.accounting.total_bytes, metadata.accounting.total_bytes

        c1_short, c2_short = cumulative_bytes(1)
        c1_long, c2_long = cumulative_bytes(30)

        # One turn: C1 is cheaper.
        assert c1_short < c2_short
        # Thirty turns: C1 has overtaken C2 decisively.
        assert c1_long > c2_long * 5

    def test_metadata_growth_is_linear_in_turns(self) -> None:
        # Doubling the turns should roughly double C2's cost, not quadruple it.
        def cumulative(turns: int) -> int:
            channel = MetadataChannel("agent_b", window=8)
            for turn in range(turns):
                channel.offer((make_event(turn),), turn=turn)
            return channel.accounting.total_bytes

        assert cumulative(20) == pytest.approx(2 * cumulative(10), rel=0.15)

    def test_more_relevant_events_survive_the_window(self) -> None:
        channel = MetadataChannel(
            "agent_b",
            window=1,
            interests=AgentInterests(
                agent_id="agent_b", owned_paths=frozenset({"src/api.py"})
            ),
        )
        injection = channel.offer(
            (
                make_event(0, event_type=EventType.READ, paths=("docs/x.md",)),
                make_event(1, event_type=EventType.WRITE, paths=("src/api.py",)),
            ),
            turn=0,
        )
        assert "src/api.py" in injection.text

    def test_an_empty_turn_costs_nothing(self) -> None:
        channel = MetadataChannel("agent_b")
        injection = channel.offer((), turn=0)
        assert injection.bytes_injected == 0
        assert injection.events_injected == 0

    def test_a_zero_window_injects_nothing_but_still_counts_availability(self) -> None:
        # The degenerate case must still distinguish "available" from
        # "injected", or a misconfiguration would look like C0.
        channel = MetadataChannel("agent_b", window=0)
        injection = channel.offer(tuple(make_event(i) for i in range(3)), turn=0)
        assert injection.events_injected == 0
        assert injection.events_available == 3
        assert not channel.accounting.received_no_coordination

    def test_a_negative_window_is_refused(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            MetadataChannel("agent_b", window=-1)

    def test_c3_uses_the_same_channel_as_c2(self) -> None:
        # If C3 also changed representation, the C2→C3 contrast would
        # confound enforcement with a second factor.
        events = tuple(make_event(i) for i in range(4))
        c2 = MetadataChannel("agent_b", arm="C2", window=4)
        c3 = MetadataChannel("agent_b", arm="C3", window=4)
        assert c2.offer(events, turn=0).text == c3.offer(events, turn=0).text

    def test_the_configuration_is_reportable(self) -> None:
        # §32: the window and weights must reach the manifest.
        config = MetadataChannel("agent_b", window=5).to_dict()
        assert config["window"] == 5
        assert set(config["weights"]) == {
            "causal_distance",
            "dependency_overlap",
            "path_overlap",
            "priority",
            "recency",
        }


class TestAccounting:
    def test_bytes_and_tokens_accumulate(self) -> None:
        channel = MetadataChannel("agent_b", window=8)
        for turn in range(3):
            channel.offer((make_event(turn),), turn=turn)
        assert channel.accounting.total_bytes > 0
        assert channel.accounting.total_tokens > 0
        assert channel.accounting.turns == 3

    def test_a_channel_that_injected_anything_is_not_isolated(self) -> None:
        channel = MetadataChannel("agent_b", window=8)
        channel.offer((make_event(0),), turn=0)
        assert not channel.accounting.received_no_coordination

    def test_the_digest_reflects_the_injected_bytes(self) -> None:
        channel = MetadataChannel("agent_b", window=8)
        first = channel.offer((make_event(0),), turn=0)
        second = channel.offer((make_event(1),), turn=1)
        assert first.digest() != second.digest()

    def test_accounting_serialises_for_the_manifest(self) -> None:
        channel = MetadataChannel("agent_b", window=4)
        channel.offer((make_event(0),), turn=0)
        data = channel.accounting.to_dict()
        assert {
            "coordination_bytes",
            "coordination_tokens",
            "events_available",
            "events_dropped",
            "events_injected",
            "received_no_coordination",
            "turns",
        } <= set(data)


class TestTokenEstimation:
    def test_empty_text_costs_nothing(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_text_costs_at_least_one_token(self) -> None:
        # Rounding down would make a real coordination cost disappear.
        assert estimate_tokens("a") == 1

    def test_the_estimate_is_monotonic_in_length(self) -> None:
        assert estimate_tokens("a" * 100) > estimate_tokens("a" * 10)

    def test_the_estimate_is_deterministic(self) -> None:
        # The C1→C2 contrast is a ratio measured the same way on both sides,
        # so determinism matters more than absolute accuracy here.
        assert len({estimate_tokens("some coordination text") for _ in range(10)}) == 1
