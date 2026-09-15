"""The relevance scorer (spec §17).

Two properties carry the experiment:

- **Determinism.** The same events, interests and turn must produce the same
  ranking every time, or a run cannot be reproduced from its seed (§40, §84).
- **Explainability.** Every score records why it was assigned. A selection
  nobody can justify is a confound: if C2 beats C0, the benefit must be
  attributable to information rather than to an unexamined ranking rule.
"""

from __future__ import annotations

import pytest

from causalmesh.events.schema import Event, EventIdentity, EventType
from causalmesh.relevance import (
    AgentInterests,
    RelevanceScorer,
    RelevanceWeights,
)

pytestmark = pytest.mark.unit

RUN = "run_001"
BASE_TIME = 1_700_000_000_000_000


def make_event(
    sequence: int = 0,
    *,
    actor: str = "agent_a",
    event_type: EventType = EventType.WRITE,
    paths: tuple[str, ...] = ("src/schema.py",),
    parent_id: str | None = None,
) -> Event:
    return Event(
        event_id=f"evt_{sequence:04d}",
        identity=EventIdentity(
            experiment_id="exp_rel",
            task_id="task_rel",
            run_id=RUN,
            agent_id=actor,
            arm="C2",
        ),
        event_type=event_type,
        sequence=sequence,
        timestamp_us=BASE_TIME + sequence,
        paths=paths,
        parent_id=parent_id,
    )


@pytest.fixture
def scorer() -> RelevanceScorer:
    return RelevanceScorer()


@pytest.fixture
def interests() -> AgentInterests:
    return AgentInterests(
        agent_id="agent_b",
        owned_paths=frozenset({"src/api.py"}),
        dependency_paths=frozenset({"src/schema.py"}),
    )


class TestDeterminism:
    def test_the_same_inputs_give_the_same_score(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        event = make_event()
        totals = {
            scorer.score(event, interests=interests, current_turn=3, event_turn=1).total
            for _ in range(20)
        }
        assert len(totals) == 1

    def test_ranking_does_not_depend_on_input_order(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # Delivery order varies with timing; a selection that depended on it
        # would not be reproducible from the seed alone.
        events = [(make_event(i), 1) for i in range(5)]
        forward = [s.event_id for s in scorer.rank(events, interests=interests, current_turn=3)]
        reverse = [
            s.event_id
            for s in scorer.rank(list(reversed(events)), interests=interests, current_turn=3)
        ]
        assert forward == reverse

    def test_ties_break_on_event_id(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # Identical events differing only by id must order predictably.
        events = [(make_event(i, paths=("unrelated.py",)), 1) for i in (2, 0, 1)]
        ranked = scorer.rank(events, interests=interests, current_turn=1)
        assert [s.event_id for s in ranked] == ["evt_0000", "evt_0001", "evt_0002"]

    def test_no_clock_or_randomness_is_consulted(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # Recency is measured in turns, not wall-clock time, so a slow run
        # and a fast one score identically.
        early = make_event(0)
        late = Event(
            event_id="evt_0000",
            identity=early.identity,
            event_type=early.event_type,
            sequence=0,
            timestamp_us=BASE_TIME + 999_999_999,
            paths=early.paths,
        )
        a = scorer.score(early, interests=interests, current_turn=2, event_turn=1)
        b = scorer.score(late, interests=interests, current_turn=2, event_turn=1)
        assert a.total == b.total


class TestComponents:
    def test_an_owned_path_scores_maximum_overlap(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        score = scorer.score(
            make_event(paths=("src/api.py",)),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.path_overlap == 1.0
        assert "owned path" in score.reason

    def test_a_declared_dependency_scores_dependency_overlap(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # The stale-dependency case (§23): a peer changed something this
        # agent's work is built on.
        score = scorer.score(
            make_event(paths=("src/schema.py",)),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.dependency_overlap == 1.0
        assert "dependency" in score.reason

    def test_an_unrelated_path_scores_no_overlap(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        score = scorer.score(
            make_event(paths=("docs/readme.md",)),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.path_overlap == 0.0
        assert score.dependency_overlap == 0.0

    def test_a_touched_path_counts_as_overlap(self, scorer: RelevanceScorer) -> None:
        interests = AgentInterests(agent_id="agent_b")
        interests.record_touch(("src/worked_on.py",))
        score = scorer.score(
            make_event(paths=("src/worked_on.py",)),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.path_overlap == 1.0

    def test_recency_decays_with_turn_age(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        event = make_event()
        now = scorer.score(event, interests=interests, current_turn=5, event_turn=5)
        one = scorer.score(event, interests=interests, current_turn=5, event_turn=4)
        old = scorer.score(event, interests=interests, current_turn=5, event_turn=0)
        assert now.recency == 1.0
        assert one.recency == 0.5
        assert now.recency > one.recency > old.recency

    def test_mutating_events_outrank_reads(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # A peer's READ tells an agent almost nothing; a WRITE may invalidate
        # work in progress.
        write = scorer.score(
            make_event(event_type=EventType.WRITE),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        read = scorer.score(
            make_event(event_type=EventType.READ),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert write.priority == 1.0
        assert read.priority == 0.0
        assert write.total > read.total

    def test_a_known_causal_parent_raises_the_score(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        event = make_event(1, parent_id="evt_0000")
        connected = scorer.score(
            event,
            interests=interests,
            current_turn=1,
            event_turn=1,
            causal_parents=frozenset({"evt_0000"}),
        )
        isolated = scorer.score(event, interests=interests, current_turn=1, event_turn=1)
        assert connected.causal_distance > isolated.causal_distance

    def test_a_pathless_event_scores_no_overlap(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        score = scorer.score(
            make_event(event_type=EventType.INTENT, paths=()),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.path_overlap == 0.0


class TestExplainability:
    def test_every_score_records_its_components(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # A single total would say "0.71" without saying whether that came
        # from path overlap or recency, and those mean different things.
        data = scorer.score(
            make_event(), interests=interests, current_turn=1, event_turn=1
        ).to_dict()
        assert {
            "causal_distance",
            "dependency_overlap",
            "path_overlap",
            "priority",
            "recency",
            "reason",
            "total",
        } <= set(data)

    def test_a_matched_event_carries_a_reason(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        score = scorer.score(
            make_event(paths=("src/api.py",)),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.reason
        assert "src/api.py" in score.reason

    def test_an_unmatched_event_says_so_explicitly(self, scorer: RelevanceScorer) -> None:
        # Silence would be indistinguishable from a missing reason.
        bare = AgentInterests(agent_id="agent_b")
        score = scorer.score(
            make_event(event_type=EventType.READ, paths=("x.py",)),
            interests=bare,
            current_turn=5,
            event_turn=0,
        )
        assert score.reason == "no relevance signal matched"

    def test_the_total_is_recomputable_from_the_components(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        # A reviewer must be able to check any score by hand.
        weights = scorer.weights
        score = scorer.score(make_event(), interests=interests, current_turn=3, event_turn=2)
        expected = (
            weights.path_overlap * score.path_overlap
            + weights.dependency_overlap * score.dependency_overlap
            + weights.causal_distance * score.causal_distance
            + weights.recency * score.recency
            + weights.priority * score.priority
        )
        assert score.total == pytest.approx(expected)


class TestWeights:
    def test_default_weights_sum_to_one(self) -> None:
        assert RelevanceWeights().total() == pytest.approx(1.0)

    def test_weights_are_configurable(self, interests: AgentInterests) -> None:
        # §18 requires the configuration to be explicit, not hard-coded.
        only_recency = RelevanceScorer(
            RelevanceWeights(
                path_overlap=0.0,
                dependency_overlap=0.0,
                causal_distance=0.0,
                recency=1.0,
                priority=0.0,
            )
        )
        score = only_recency.score(
            make_event(paths=("src/api.py",)),
            interests=interests,
            current_turn=1,
            event_turn=1,
        )
        assert score.total == pytest.approx(1.0)


class TestRanking:
    def test_the_most_relevant_event_ranks_first(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        events = [
            (make_event(0, event_type=EventType.READ, paths=("docs/x.md",)), 0),
            (make_event(1, event_type=EventType.WRITE, paths=("src/api.py",)), 1),
            (make_event(2, event_type=EventType.READ, paths=("other.py",)), 0),
        ]
        ranked = scorer.rank(events, interests=interests, current_turn=1)
        assert ranked[0].event_id == "evt_0001"

    def test_ranking_returns_a_score_for_every_event(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        events = [(make_event(i), 1) for i in range(6)]
        assert len(scorer.rank(events, interests=interests, current_turn=2)) == 6

    def test_ranking_is_descending_by_total(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        events = [
            (make_event(0, paths=("src/api.py",)), 1),
            (make_event(1, event_type=EventType.READ, paths=("z.py",)), 0),
            (make_event(2, paths=("src/schema.py",)), 1),
        ]
        totals = [s.total for s in scorer.rank(events, interests=interests, current_turn=1)]
        assert totals == sorted(totals, reverse=True)

    def test_an_empty_input_ranks_to_nothing(
        self, scorer: RelevanceScorer, interests: AgentInterests
    ) -> None:
        assert scorer.rank([], interests=interests, current_turn=1) == []
