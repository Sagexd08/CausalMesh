"""Scenario parsing and validation (spec §9, §36).

Scripts are validated up front so a malformed scenario fails before a run
starts. A run that dies halfway still produces evidence (§81), but evidence
of a typo is not what the experiment is for.

Unknown keys are refused rather than ignored: a misspelled option would
otherwise silently change what the experiment ran, and the resulting data
would look valid.
"""

from __future__ import annotations

import pytest

from causalmesh.agents import (
    ActionKind,
    AgentScript,
    Scenario,
    ScriptError,
    parse_duration_us,
)

pytestmark = pytest.mark.unit


class TestDurations:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("2s", 2_000_000),
            ("500ms", 500_000),
            ("100us", 100),
            ("1m", 60_000_000),
            ("1.5s", 1_500_000),
        ],
    )
    def test_units_are_parsed(self, text: str, expected: int) -> None:
        assert parse_duration_us(text) == expected

    def test_a_bare_number_is_microseconds(self) -> None:
        # Matching the event schema's unit. Treating it as seconds would be a
        # silent factor of a million, very hard to notice in a result.
        assert parse_duration_us(1000) == 1000

    @pytest.mark.parametrize("bad", ["2 seconds", "soon", "", "2x", "-3s"])
    def test_unparseable_durations_are_refused(self, bad: str) -> None:
        with pytest.raises(ScriptError):
            parse_duration_us(bad)

    def test_a_negative_number_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="negative"):
            parse_duration_us(-1)


class TestCompactForm:
    """§9's example syntax must parse exactly as written."""

    def test_the_specification_example_parses(self) -> None:
        scenario = Scenario.from_yaml(
            """
            agent_a:
              actions:
                - read: src/schema.py
                - modify: {path: src/schema.py, old: "a", new: "b"}
                - write: src/schema.py

            agent_b:
              actions:
                - read: src/schema.py
                - wait: 2s
                - modify: {path: src/api.py, old: "x", new: "y"}
                - write: src/api.py
            """
        )
        assert scenario.agent_ids() == ("agent_a", "agent_b")
        assert len(scenario.agents["agent_b"].actions) == 4
        assert scenario.agents["agent_b"].actions[1].kind is ActionKind.WAIT
        assert scenario.agents["agent_b"].actions[1].duration_us == 2_000_000

    def test_a_bare_verb_needs_no_argument(self) -> None:
        script = AgentScript.from_dict("agent_a", {"actions": ["test"]})
        assert script.actions[0].kind is ActionKind.TEST

    def test_the_expanded_form_is_equivalent(self) -> None:
        compact = AgentScript.from_dict("a", {"actions": [{"read": "src/x.py"}]})
        expanded = AgentScript.from_dict(
            "a", {"actions": [{"kind": "read", "path": "src/x.py"}]}
        )
        assert compact.actions[0] == expanded.actions[0]


class TestValidation:
    def test_an_unknown_verb_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="unknown action"):
            AgentScript.from_dict("a", {"actions": [{"teleport": "x"}]})

    def test_an_unknown_option_is_refused(self) -> None:
        # A typo must not silently change what the experiment ran.
        with pytest.raises(ScriptError, match="unrecognised option"):
            AgentScript.from_dict("a", {"actions": [{"read": "x.py", "colour": "red"}]})

    def test_a_path_action_without_a_path_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="requires a path"):
            AgentScript.from_dict("a", {"actions": [{"kind": "read"}]})

    def test_rename_without_a_destination_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="destination"):
            AgentScript.from_dict("a", {"actions": [{"rename": "a.py"}]})

    def test_modify_without_old_and_new_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="old.*new"):
            AgentScript.from_dict("a", {"actions": [{"modify": "a.py"}]})

    def test_two_verbs_in_one_action_are_refused(self) -> None:
        with pytest.raises(ScriptError, match="exactly one action verb"):
            AgentScript.from_dict("a", {"actions": [{"read": "a.py", "write": "b.py"}]})

    def test_an_empty_scenario_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="non-empty"):
            Scenario.from_dict({})

    def test_a_non_list_actions_field_is_refused(self) -> None:
        with pytest.raises(ScriptError, match="expected a list"):
            AgentScript.from_dict("a", {"actions": "read src/x.py"})

    def test_the_error_names_the_offending_action(self) -> None:
        # A scenario may be long; the message must locate the problem.
        with pytest.raises(ScriptError, match=r"agent_a\.actions\[1\]"):
            AgentScript.from_dict(
                "agent_a", {"actions": [{"read": "a.py"}, {"nonsense": "x"}]}
            )


class TestFailureModes:
    """§9 and §22: crashes, stalls and retries are first-class."""

    def test_a_crash_action_parses(self) -> None:
        script = AgentScript.from_dict("a", {"actions": [{"crash": "simulated failure"}]})
        assert script.actions[0].kind is ActionKind.CRASH
        assert script.actions[0].note == "simulated failure"

    def test_a_stall_carries_a_duration(self) -> None:
        script = AgentScript.from_dict("a", {"actions": [{"stall": "5s"}]})
        assert script.actions[0].kind is ActionKind.STALL
        assert script.actions[0].duration_us == 5_000_000

    def test_retries_parse(self) -> None:
        script = AgentScript.from_dict(
            "a", {"actions": [{"write": "a.py", "retries": 3}]}
        )
        assert script.actions[0].retries == 3


class TestCoordinationSensitivity:
    """§37: a scenario must demonstrably contest something."""

    def test_a_contested_path_is_detected(self) -> None:
        scenario = Scenario.from_dict(
            {
                "agent_a": {"actions": [{"write": "src/schema.py"}]},
                "agent_b": {"actions": [{"write": "src/schema.py"}]},
            }
        )
        assert scenario.contested_paths() == frozenset({"src/schema.py"})

    def test_disjoint_writers_contest_nothing(self) -> None:
        # A scenario like this cannot distinguish the arms, and the task
        # quality gate must be able to say so.
        scenario = Scenario.from_dict(
            {
                "agent_a": {"actions": [{"write": "src/a.py"}]},
                "agent_b": {"actions": [{"write": "src/b.py"}]},
            }
        )
        assert scenario.contested_paths() == frozenset()

    def test_shared_reads_are_not_contention(self) -> None:
        # Two agents reading the same file do not conflict; only writes do.
        scenario = Scenario.from_dict(
            {
                "agent_a": {"actions": [{"read": "src/schema.py"}]},
                "agent_b": {"actions": [{"read": "src/schema.py"}]},
            }
        )
        assert scenario.contested_paths() == frozenset()

    def test_a_write_and_a_read_are_not_contention(self) -> None:
        scenario = Scenario.from_dict(
            {
                "agent_a": {"actions": [{"write": "src/schema.py"}]},
                "agent_b": {"actions": [{"read": "src/schema.py"}]},
            }
        )
        assert scenario.contested_paths() == frozenset()

    def test_different_mutating_verbs_still_contest(self) -> None:
        scenario = Scenario.from_dict(
            {
                "agent_a": {"actions": [{"write": "src/x.py"}]},
                "agent_b": {
                    "actions": [{"modify": {"path": "src/x.py", "old": "a", "new": "b"}}]
                },
            }
        )
        assert scenario.contested_paths() == frozenset({"src/x.py"})


class TestDeclaredInterests:
    def test_owns_and_depends_on_are_captured(self) -> None:
        # Interests are declared by the task, never inferred from behaviour
        # (§17), so they must survive parsing.
        script = AgentScript.from_dict(
            "agent_b",
            {
                "owns": ["src/api.py"],
                "depends_on": ["src/schema.py"],
                "actions": [{"read": "src/schema.py"}],
            },
        )
        assert script.owned_paths == frozenset({"src/api.py"})
        assert script.dependency_paths == frozenset({"src/schema.py"})

    def test_paths_touched_covers_both_ends_of_a_rename(self) -> None:
        script = AgentScript.from_dict(
            "a", {"actions": [{"rename": "old.py", "to": "new.py"}]}
        )
        assert script.paths_touched() == frozenset({"old.py", "new.py"})


class TestSerialisation:
    def test_a_scenario_round_trips_through_dicts(self) -> None:
        # Scenarios reach the run manifest (§32), so they must serialise.
        original = Scenario.from_dict(
            {"agent_a": {"actions": [{"read": "a.py"}, {"wait": "1s"}]}}
        )
        assert Scenario.from_dict(
            {
                agent_id: {
                    "actions": [
                        {k: v for k, v in action.items() if v not in (None, 0)}
                        for action in data["actions"]
                    ]
                }
                for agent_id, data in original.to_dict().items()
            }
        ).agent_ids() == original.agent_ids()

    def test_actions_serialise_with_every_field(self) -> None:
        action = AgentScript.from_dict(
            "a", {"actions": [{"write": "x.py", "content": "hello"}]}
        ).actions[0]
        assert action.to_dict()["content"] == "hello"
        assert action.to_dict()["kind"] == "write"
