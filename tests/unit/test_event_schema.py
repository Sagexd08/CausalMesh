"""Unit tests for the event schema (spec §16, §29, §10)."""

from __future__ import annotations

import dataclasses
import json

import pytest

from causalmesh.events.canonical import CanonicalizationError
from causalmesh.events.schema import (
    SCHEMA_VERSION,
    Event,
    EventIdentity,
    EventType,
    EventValidationError,
    micros_to_rfc3339,
    utc_now_micros,
)

pytestmark = pytest.mark.unit


def make_identity(**overrides: str) -> EventIdentity:
    base = {
        "experiment_id": "exp-001",
        "task_id": "task-schema-handler",
        "run_id": "run-001",
        "agent_id": "agent-A",
        "arm": "C2",
    }
    return EventIdentity(**{**base, **overrides})


def make_event(**overrides: object) -> Event:
    base: dict[str, object] = {
        "event_id": "evt-000001",
        "identity": make_identity(),
        "event_type": EventType.WRITE,
        "sequence": 1,
        "timestamp_us": 1_757_000_000_000_000,
    }
    return Event(**{**base, **overrides})  # type: ignore[arg-type]


class TestIdentity:
    def test_valid_identity_is_accepted(self) -> None:
        assert make_identity().agent_id == "agent-A"

    @pytest.mark.parametrize(
        "bad",
        ["", "has space", "has/slash", "-leading", "x" * 200, "unicode-café"],
        ids=["empty", "space", "slash", "leading-dash", "too-long", "non-ascii"],
    )
    def test_invalid_identifiers_are_rejected(self, bad: str) -> None:
        with pytest.raises(EventValidationError):
            make_identity(agent_id=bad)

    def test_identity_is_immutable(self) -> None:
        identity = make_identity()
        with pytest.raises(dataclasses.FrozenInstanceError):
            identity.agent_id = "agent-B"  # type: ignore[misc]

    def test_all_identity_fields_appear_in_canonical_form(self) -> None:
        # Identity must never be inferable from a filename (§10), so every
        # field has to be carried in the signed bytes.
        canonical = make_identity().to_canonical_dict()
        assert set(canonical) == {
            "agent_id",
            "arm",
            "experiment_id",
            "run_id",
            "task_id",
        }


class TestEventValidation:
    def test_minimal_event_is_valid(self) -> None:
        assert make_event().schema_version == SCHEMA_VERSION

    def test_event_is_immutable(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            make_event().sequence = 99  # type: ignore[misc]

    def test_event_type_must_be_enum_not_string(self) -> None:
        with pytest.raises(EventValidationError, match="EventType"):
            make_event(event_type="WRITE")

    @pytest.mark.parametrize("field", ["sequence", "timestamp_us"])
    def test_bool_is_rejected_where_int_expected(self, field: str) -> None:
        # bool subclasses int, so True would otherwise pass as sequence 1.
        with pytest.raises(EventValidationError, match=field):
            make_event(**{field: True})

    @pytest.mark.parametrize("field", ["sequence", "timestamp_us"])
    def test_negative_values_are_rejected(self, field: str) -> None:
        with pytest.raises(EventValidationError, match=field):
            make_event(**{field: -1})

    def test_float_sequence_is_rejected(self) -> None:
        with pytest.raises(EventValidationError, match="sequence"):
            make_event(sequence=1.0)

    def test_mutable_paths_are_rejected(self) -> None:
        # A list would let an event mutate after it was hashed.
        with pytest.raises(EventValidationError, match="tuple"):
            make_event(paths=["src/a.py"])

    def test_non_string_path_entries_are_rejected(self) -> None:
        with pytest.raises(EventValidationError, match="paths"):
            make_event(paths=("ok.py", 42))

    def test_invalid_parent_id_is_rejected(self) -> None:
        with pytest.raises(EventValidationError, match="parent_id"):
            make_event(parent_id="not a valid id")

    def test_none_parent_is_allowed(self) -> None:
        assert make_event(parent_id=None).parent_id is None


class TestCanonicalForm:
    def test_canonical_bytes_are_deterministic(self) -> None:
        assert make_event().canonical_bytes() == make_event().canonical_bytes()

    def test_canonical_bytes_parse_as_json(self) -> None:
        parsed = json.loads(make_event().canonical_bytes().decode("utf-8"))
        assert parsed["event_type"] == "WRITE"
        assert parsed["identity"]["agent_id"] == "agent-A"

    def test_paths_are_sorted_so_ordering_is_not_significant(self) -> None:
        # A set of touched paths has no inherent order; two agents listing the
        # same paths differently must produce identical bytes.
        first = make_event(paths=("b.py", "a.py"))
        second = make_event(paths=("a.py", "b.py"))
        assert first.canonical_bytes() == second.canonical_bytes()

    def test_reference_order_is_significant(self) -> None:
        # References are ordered: they describe a sequence of causes.
        first = make_event(references=("evt-1", "evt-2"))
        second = make_event(references=("evt-2", "evt-1"))
        assert first.canonical_bytes() != second.canonical_bytes()

    def test_unicode_paths_are_normalized(self) -> None:
        composed = make_event(paths=("src/café.py",))
        decomposed = make_event(paths=("src/café.py",))
        assert composed.canonical_bytes() == decomposed.canonical_bytes()

    def test_changing_any_field_changes_the_bytes(self) -> None:
        baseline = make_event().canonical_bytes()
        variants = [
            make_event(sequence=2),
            make_event(timestamp_us=1_757_000_000_000_001),
            make_event(event_type=EventType.READ),
            make_event(event_id="evt-000002"),
            make_event(paths=("x.py",)),
            make_event(parent_id="evt-000000"),
            make_event(payload={"k": "v"}),
            make_event(identity=make_identity(agent_id="agent-B")),
            make_event(identity=make_identity(arm="C3")),
        ]
        for variant in variants:
            assert variant.canonical_bytes() != baseline

    def test_float_payload_is_rejected_at_serialization(self) -> None:
        # The schema permits any dict payload; canonicalization is where an
        # unserializable value must fail, loudly rather than by rounding.
        with pytest.raises(CanonicalizationError, match="float"):
            make_event(payload={"duration": 1.5}).canonical_bytes()

    def test_schema_version_is_present_in_bytes(self) -> None:
        parsed = json.loads(make_event().canonical_bytes().decode("utf-8"))
        assert parsed["schema_version"] == SCHEMA_VERSION


class TestTimestamps:
    def test_utc_now_micros_is_a_plausible_int(self) -> None:
        now = utc_now_micros()
        assert isinstance(now, int) and not isinstance(now, bool)
        assert now > 1_700_000_000_000_000  # after 2023

    def test_rfc3339_rendering_is_utc(self) -> None:
        assert micros_to_rfc3339(0) == "1970-01-01T00:00:00.000000Z"

    def test_rfc3339_preserves_microseconds(self) -> None:
        assert micros_to_rfc3339(1_757_000_000_123_456).endswith("123456Z")


class TestPolicyVerdictEventType:
    def test_policy_verdict_is_a_member(self) -> None:
        assert EventType.POLICY_VERDICT == "POLICY_VERDICT"

    def test_policy_verdict_round_trips_through_canonicalization(self) -> None:
        identity = EventIdentity(
            experiment_id="exp1",
            task_id="task1",
            run_id="run1",
            agent_id="policy_gate",
            arm="C3",
        )
        event = Event(
            event_id="run1_verdict_0",
            identity=identity,
            event_type=EventType.POLICY_VERDICT,
            sequence=0,
            timestamp_us=1_700_000_000_000_000,
            payload={"allowed": False, "reason": "test", "rule": "ownership"},
        )
        canonical = event.to_canonical_dict()
        assert canonical["event_type"] == "POLICY_VERDICT"
        # Re-canonicalizing the same structure must be byte-identical —
        # this is the property the whole hash chain depends on.
        assert event.canonical_bytes() == event.canonical_bytes()


class TestIntegrationTestResultEventType:
    def test_is_a_member_distinct_from_an_agents_test_event(self) -> None:
        # TEST is an agent running tests inside its own workspace; this is the
        # harness measuring the integrated result. Conflating them would make
        # an agent's tests indistinguishable from the run's verdict.
        assert EventType.INTEGRATION_TEST_RESULT == "INTEGRATION_TEST_RESULT"
        assert EventType.INTEGRATION_TEST_RESULT != EventType.TEST

    def test_round_trips_with_an_unknown_exit_code(self) -> None:
        identity = EventIdentity(
            experiment_id="exp1",
            task_id="task1",
            run_id="run1",
            agent_id="integration_test",
            arm="C2",
        )
        event = Event(
            event_id="run1_integration_test",
            identity=identity,
            event_type=EventType.INTEGRATION_TEST_RESULT,
            sequence=0,
            timestamp_us=1_700_000_000_000_000,
            payload={"command": ["pytest"], "exit_code": None, "ran": False},
        )
        canonical = event.to_canonical_dict()
        assert canonical["event_type"] == "INTEGRATION_TEST_RESULT"
        # A test that never ran is recorded as null, never as a passing 0.
        assert canonical["payload"]["exit_code"] is None
        assert event.canonical_bytes() == event.canonical_bytes()
