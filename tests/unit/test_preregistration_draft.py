"""Drift guards for the preregistration draft and the staleness note.

`docs/preregistration-draft.md` restates design facts that live in code, and
`docs/staleness-estimators-needed.md` cites persisted field names. A document
that quietly disagrees with the code is worse than none, so these tests fail
when a cited fact changes. They assert facts, not wording.

They do not test that any decision has been made: the draft exists precisely
to list decisions no one has made yet, and the gate must stay closed.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from causalmesh.channels.base import InjectionAccounting
from causalmesh.events.schema import Event, EventType
from causalmesh.experiments import PROFILES, ProfileError, profile
from causalmesh.experiments.arms import ARM_IDS, PRIMARY_CONTRASTS
from causalmesh.tasks import load_tasks
from causalmesh.tasks.definition import TaskFamily

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
PREREG = (ROOT / "docs" / "preregistration-draft.md").read_text(encoding="utf-8")
STALENESS = (ROOT / "docs" / "staleness-estimators-needed.md").read_text(encoding="utf-8")


class TestPreregistrationDraft:
    def test_the_gate_is_still_closed(self) -> None:
        assert PROFILES["confirmatory"].gated is True
        with pytest.raises(ProfileError):
            profile("confirmatory")

    def test_the_scale_the_draft_cites_is_the_scale_in_code(self) -> None:
        confirmatory = profile("confirmatory", allow_gated=True)
        assert confirmatory.repetitions == 120
        assert confirmatory.arms == ARM_IDS
        assert confirmatory.max_tasks is None
        assert confirmatory.run_count(4) == 1920
        assert confirmatory.run_count(2) == 960
        assert "1920" in PREREG and "960" in PREREG and "120" in PREREG

    def test_the_task_discrepancy_the_draft_reports_is_still_true(self) -> None:
        """The draft says only two tasks are plannable (imports are excluded).
        If a task is added, the draft's run count needs revisiting."""
        tasks = load_tasks(ROOT / "tasks")
        eligible = [t for t in tasks if t.family != TaskFamily.COOPERBENCH_IMPORT]
        assert len(eligible) == 2, (
            "the number of plannable tasks changed; update docs/preregistration-draft.md 1.1"
        )
        for task in eligible:
            assert task.task_id in PREREG

    def test_every_arm_and_contrast_is_named(self) -> None:
        for arm_id in ARM_IDS:
            assert arm_id in PREREG
        for contrast in PRIMARY_CONTRASTS:
            assert contrast.name in PREREG
            assert contrast.baseline in PREREG and contrast.treatment in PREREG

    def test_the_owner_decisions_are_listed_and_not_answered(self) -> None:
        required = (
            "TODO-HYPOTHESES",
            "TODO-PRIMARY",
            "TODO-ALPHA",
            "TODO-MODEL",
            "TODO-MULTIPLICITY",
            "TODO-STOPPING",
            "TODO-EXCLUSIONS",
            "TODO-COMPUTE",
            "TODO-MOCK-VS-REAL",
            "TODO-TASKS",
            "TODO-SEED",
        )
        for marker in required:
            assert f"### {marker}" in PREREG, f"{marker} should be a defined decision heading"
        assert PREREG.count("TODO(owner)") >= len(required)
        assert "DRAFT" in PREREG

    def test_the_outcome_definition_it_cites_is_the_coded_one(self) -> None:
        from causalmesh.tasks.outcome import TaskOutcome

        names = {f.name for f in dataclasses.fields(TaskOutcome)}
        assert {"succeeded", "tests_passed", "divergence_absent"} <= names
        for name in ("succeeded", "tests_passed", "divergence_absent"):
            assert name in PREREG

    def test_the_documents_are_ascii(self) -> None:
        for text in (PREREG, STALENESS):
            offenders = sorted({c for c in text if ord(c) > 127})
            assert offenders == []


class TestStalenessNote:
    def test_it_says_nothing_is_implemented(self) -> None:
        assert "No staleness estimator is implemented" in STALENESS

    def test_no_estimator_is_being_smuggled_in_by_this_note(self) -> None:
        """The note must not define the quantities. It may name them."""
        lowered = STALENESS.lower()
        assert "must not be read as doing so" in lowered

    def test_the_event_fields_it_cites_exist(self) -> None:
        names = {f.name for f in dataclasses.fields(Event)}
        for field_name in (
            "event_id",
            "identity",
            "event_type",
            "sequence",
            "timestamp_us",
            "paths",
            "references",
            "parent_id",
            "payload",
        ):
            assert field_name in names
            assert field_name in STALENESS
        for member in ("WRITE", "CREATE", "MODIFY", "DELETE", "RENAME", "CLAIM", "COMMIT"):
            assert EventType(member)
            assert member in STALENESS

    def test_the_accounting_keys_it_cites_exist(self) -> None:
        keys = set(InjectionAccounting(agent_id="a").to_dict())
        for key in (
            "turns",
            "coordination_bytes",
            "coordination_tokens",
            "events_available",
            "events_selected",
            "events_injected",
            "events_dropped",
            "turn_digests",
        ):
            assert key in keys
            assert key in STALENESS

    def test_the_two_observation_keys_it_warns_about_really_differ(self) -> None:
        """Section 3.2 of the note: scripted uses `event_ids`, the model agent
        uses `events`. If they are ever aligned, the note is stale."""
        mock_src = (ROOT / "src/causalmesh/agents/mock.py").read_text(encoding="utf-8")
        model_src = (ROOT / "src/causalmesh/adapters/model_agent.py").read_text(encoding="utf-8")
        assert '"event_ids"' in mock_src
        assert '"events": list(events)' in model_src

    def test_per_turn_injection_counts_are_still_not_persisted(self) -> None:
        """Section 3.3: only totals and digests are kept per agent. If a
        per-turn list is added, that gap in the note is closed and it should
        be rewritten."""
        keys = set(InjectionAccounting(agent_id="a").to_dict())
        assert not {"per_turn", "turn_injections", "turn_counts"} & keys
