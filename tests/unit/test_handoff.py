"""The handoff package record shape (backlog: "Agent handoff package on recovery").

Only the shape is built, so these tests pin the properties the shape exists
to have: unknown stays distinct from empty, the serialisation is
deterministic and round-trips, and nothing machine-specific can get in.
"""

from __future__ import annotations

import json

import pytest

from causalmesh.scheduler import (
    HANDOFF_SCHEMA_VERSION,
    DiffEntry,
    HandoffError,
    HandoffPackage,
    PriorDecision,
    TestResult,
)

pytestmark = pytest.mark.unit

A = "a" * 64
B = "b" * 64
C = "c" * 64


def make_package(**overrides) -> HandoffPackage:
    fields = {
        "run_id": "run_001",
        "task_id": "schema_handler_widen",
        "task_hash": A,
        "from_agent": "agent_a",
        "to_agent": "agent_b",
        "repository_digest": B,
        "objective": "widen the schema and update the handler",
        "diff": (
            DiffEntry(path="src/handler.py", change="modified", before_digest=A, after_digest=B),
            DiffEntry(path="src/new.py", change="added", after_digest=C, patch="+x = 1\n"),
        ),
        "test_results": (TestResult(command=("pytest", "-q"), exit_code=1, passed=False),),
        "prior_decisions": (
            PriorDecision(event_id="run_001_verdict_0", kind="POLICY_VERDICT", summary="allowed"),
        ),
    }
    fields.update(overrides)
    return HandoffPackage(**fields)


class TestUnknownIsNotEmpty:
    def test_an_uncomputed_diff_is_none_not_an_empty_diff(self) -> None:
        package = make_package(diff=None)
        assert package.diff is None
        assert package.to_dict()["diff"] is None

    def test_a_computed_empty_diff_is_distinct_from_an_uncomputed_one(self) -> None:
        computed = make_package(diff=())
        unknown = make_package(diff=None)
        assert computed.to_dict()["diff"] == []
        assert computed.to_json() != unknown.to_json()
        assert computed.digest() != unknown.digest()

    def test_uncomputed_test_results_are_not_a_clean_bill(self) -> None:
        package = make_package(test_results=None)
        assert package.test_results is None
        assert package.to_dict()["test_results"] is None

    def test_a_test_result_can_have_an_unknown_outcome(self) -> None:
        result = TestResult(command=("pytest",))
        assert result.exit_code is None
        assert result.passed is None

    def test_an_unchosen_successor_is_none(self) -> None:
        assert make_package(to_agent=None).to_dict()["to_agent"] is None

    def test_a_record_that_omits_test_results_is_refused_not_read_as_unknown(self) -> None:
        data = make_package().to_dict()
        del data["test_results"]
        with pytest.raises(HandoffError, match="missing"):
            HandoffPackage.from_dict(data)


class TestRoundTrip:
    def test_dict_round_trip_is_lossless(self) -> None:
        package = make_package()
        assert HandoffPackage.from_dict(package.to_dict()) == package

    def test_json_round_trip_is_lossless(self) -> None:
        package = make_package()
        assert HandoffPackage.from_json(package.to_json()) == package

    def test_a_minimal_package_round_trips(self) -> None:
        package = make_package(
            to_agent=None, objective=None, diff=None, test_results=None, prior_decisions=()
        )
        assert HandoffPackage.from_dict(package.to_dict()) == package

    def test_the_dict_is_plain_json(self) -> None:
        data = make_package().to_dict()
        assert json.loads(json.dumps(data)) == data


class TestDeterminism:
    def test_the_same_package_serialises_to_the_same_bytes(self) -> None:
        assert make_package().to_json() == make_package().to_json()
        assert make_package().digest() == make_package().digest()

    def test_the_serialisation_is_canonical(self) -> None:
        text = make_package().to_json()
        assert text == json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"))

    def test_the_digest_survives_a_round_trip(self) -> None:
        package = make_package()
        assert HandoffPackage.from_json(package.to_json()).digest() == package.digest()

    def test_the_digest_changes_when_any_field_does(self) -> None:
        base = make_package()
        assert make_package(repository_digest=C).digest() != base.digest()
        assert make_package(objective="different").digest() != base.digest()
        assert make_package(prior_decisions=()).digest() != base.digest()

    def test_the_record_carries_no_clock_or_host(self) -> None:
        text = make_package().to_json().lower()
        for forbidden in ("timestamp", "time", "host", "machine", "pid", "uuid"):
            assert f'"{forbidden}' not in text

    def test_unsorted_diff_entries_are_refused_rather_than_reordered(self) -> None:
        # Two orderings of one change would be two digests for one fact.
        later = DiffEntry(path="z.py", change="added", after_digest=A)
        earlier = DiffEntry(path="a.py", change="added", after_digest=B)
        with pytest.raises(HandoffError, match="sorted"):
            make_package(diff=(later, earlier))


class TestValidation:
    @pytest.mark.parametrize(
        "path", ["/etc/passwd", "C:\\work\\x.py", "src\\x.py", "../x.py", "a//b.py", ""]
    )
    def test_paths_must_be_repository_relative(self, path: str) -> None:
        with pytest.raises(HandoffError):
            DiffEntry(path=path, change="added", after_digest=A)

    def test_an_added_file_cannot_have_a_before_digest(self) -> None:
        with pytest.raises(HandoffError, match="before_digest"):
            DiffEntry(path="x.py", change="added", before_digest=A, after_digest=B)

    def test_a_deleted_file_cannot_have_an_after_digest(self) -> None:
        with pytest.raises(HandoffError, match="after_digest"):
            DiffEntry(path="x.py", change="deleted", before_digest=A, after_digest=B)

    def test_a_modified_file_needs_both_digests(self) -> None:
        with pytest.raises(HandoffError):
            DiffEntry(path="x.py", change="modified", after_digest=B)

    def test_an_unknown_change_kind_is_refused(self) -> None:
        with pytest.raises(HandoffError, match="change"):
            DiffEntry(path="x.py", change="teleported", after_digest=A)

    def test_digests_must_be_sha256_hex(self) -> None:
        with pytest.raises(HandoffError, match="sha256"):
            make_package(repository_digest="not-a-digest")
        with pytest.raises(HandoffError, match="sha256"):
            make_package(task_hash="A" * 64)

    def test_a_handoff_to_the_same_agent_is_not_a_handoff(self) -> None:
        with pytest.raises(HandoffError, match="different"):
            make_package(to_agent="agent_a")

    def test_passed_cannot_contradict_the_exit_code(self) -> None:
        with pytest.raises(HandoffError, match="contradicts"):
            TestResult(command=("pytest",), exit_code=1, passed=True)

    def test_passed_cannot_be_asserted_without_an_exit_code(self) -> None:
        with pytest.raises(HandoffError, match="unknown"):
            TestResult(command=("pytest",), passed=True)

    def test_a_test_result_needs_a_command(self) -> None:
        with pytest.raises(HandoffError, match="command"):
            TestResult(command=())

    def test_an_unknown_field_on_the_wire_is_refused(self) -> None:
        data = make_package().to_dict()
        data["confidence"] = 0.9
        with pytest.raises(HandoffError, match="unknown"):
            HandoffPackage.from_dict(data)

    def test_a_future_schema_version_is_refused(self) -> None:
        data = make_package().to_dict()
        data["schema_version"] = HANDOFF_SCHEMA_VERSION + 1
        with pytest.raises(HandoffError, match="schema_version"):
            HandoffPackage.from_dict(data)

    def test_invalid_json_is_a_handoff_error(self) -> None:
        with pytest.raises(HandoffError, match="JSON"):
            HandoffPackage.from_json("{nope")

    def test_the_package_is_frozen(self) -> None:
        package = make_package()
        with pytest.raises(AttributeError):
            package.run_id = "other"  # type: ignore[misc]
