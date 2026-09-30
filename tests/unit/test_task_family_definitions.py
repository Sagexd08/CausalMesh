"""The interface_consumer and shared_utility_refactor task definitions (spec §35, §36).

Structure only. Whether the coordination dependency actually exists is the
§37 gate's question and costs real execution, so it is answered in
`tests/integration/test_task_families.py`. What can be checked statically is
that each definition builds the dependency it claims to: a cross-agent
write to a declared dependency, a stale branch and an informed branch that
differ in exactly the marker, and no contention.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from causalmesh.agents.script import ActionKind, Scenario
from causalmesh.tasks import TaskDefinition, TaskFamily, load_tasks, validate_structure

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"

# task id -> (family, provider path, consumer path, stale marker)
TASKS = {
    "interface_consumer": (
        TaskFamily.INTERFACE_CONSUMER,
        "src/pricing.py",
        "src/cart.py",
        "pricing.quote(item)",
    ),
    "shared_utility_refactor": (
        TaskFamily.SHARED_UTILITY_REFACTOR,
        "src/textutil.py",
        "src/tags.py",
        "textutil.slugify(",
    ),
}


@pytest.fixture(params=sorted(TASKS))
def case(request):
    task = TaskDefinition.from_yaml(REPO / "tasks" / f"{request.param}.yaml")
    return task, *TASKS[request.param]


class TestStructure:
    def test_it_validates_with_no_errors_or_warnings(self, case) -> None:
        task, *_ = case
        report = validate_structure(task, fixtures_root=FIXTURES)
        assert report.valid, [i.detail for i in report.issues]
        assert report.issues == []

    def test_it_declares_its_family(self, case) -> None:
        task, family, *_ = case
        assert task.family == family

    def test_its_fixture_exists_and_has_an_integration_test(self, case) -> None:
        task, *_ = case
        assert (FIXTURES / task.fixture / "tests" / "test_integration.py").is_file()

    def test_nothing_is_contested(self, case) -> None:
        task, *_ = case
        scenario = Scenario.from_dict(task.scenario)
        assert task.contested_paths == frozenset()
        assert scenario.contested_paths() == frozenset()

    def test_both_tasks_are_in_the_loaded_suite(self) -> None:
        loaded = {t.task_id for t in load_tasks(REPO / "tasks")}
        assert set(TASKS) <= loaded

    def test_the_content_hash_is_stable_and_distinct(self) -> None:
        tasks = [TaskDefinition.from_yaml(REPO / "tasks" / f"{t}.yaml") for t in sorted(TASKS)]
        assert len({t.content_hash() for t in tasks}) == len(tasks)
        assert all(t.content_hash() == t.content_hash() for t in tasks)


class TestTheDependencyIsBuiltIn:
    """The coordination dependency is by construction, and these show where."""

    def test_agent_b_depends_on_a_path_only_agent_a_writes(self, case) -> None:
        task, _, provider, _consumer, _marker = case
        scenario = Scenario.from_dict(task.scenario)
        writers = {
            agent_id
            for agent_id, script in scenario.agents.items()
            for action in script.actions
            if action.kind is ActionKind.WRITE and action.path == provider
        }
        assert writers == {"agent_a"}
        assert provider in task.role_for("agent_b").depends_on
        assert provider in task.role_for("agent_a").owns

    def test_the_consumer_is_owned_and_written_by_agent_b_alone(self, case) -> None:
        task, _, _provider, consumer, _marker = case
        scenario = Scenario.from_dict(task.scenario)
        assert consumer in task.role_for("agent_b").owns
        assert consumer not in task.role_for("agent_a").owns
        assert all(action.path != consumer for action in scenario.agents["agent_a"].actions)

    def test_agent_b_has_one_informed_and_one_uninformed_write_to_the_consumer(self, case) -> None:
        task, _, provider, consumer, _marker = case
        actions = Scenario.from_dict(task.scenario).agents["agent_b"].actions
        writes = [a for a in actions if a.kind is ActionKind.WRITE and a.path == consumer]
        assert len(writes) == 2
        assert {w.if_informed_about for w in writes} == {provider, None}
        assert {w.if_uninformed_about for w in writes} == {provider, None}

    def test_agent_b_reads_the_provider_before_it_deliberates(self, case) -> None:
        # The stale-read shape (§23): read, wait, then write.
        task, _, provider, *_ = case
        kinds = [
            (a.kind, a.path) for a in Scenario.from_dict(task.scenario).agents["agent_b"].actions
        ]
        assert kinds[0] == (ActionKind.READ, provider)
        assert kinds[1][0] is ActionKind.WAIT

    def test_the_stale_marker_is_only_in_the_uninformed_branch(self, case) -> None:
        task, _, _provider, consumer, marker = case
        assert task.success.divergence_file == consumer
        assert task.success.divergence_marker == marker
        actions = Scenario.from_dict(task.scenario).agents["agent_b"].actions
        informed = next(a for a in actions if a.if_informed_about and a.path == consumer)
        uninformed = next(a for a in actions if a.if_uninformed_about and a.path == consumer)
        assert marker not in informed.content
        assert marker in uninformed.content

    def test_the_providers_change_is_breaking(self, case) -> None:
        # No shim: the old call shape must not survive in the provider, or a
        # stale consumer could never fail and the task would measure nothing.
        task, _, provider, _consumer, _marker = case
        actions = Scenario.from_dict(task.scenario).agents["agent_a"].actions
        written = next(a for a in actions if a.kind is ActionKind.WRITE and a.path == provider)
        assert "def quote(item):" not in written.content
        assert "slugify" not in written.content

    def test_the_fixture_starts_in_the_old_shape(self, case) -> None:
        # The baseline really is the pre-change interface the script changes.
        task, _, provider, _consumer, _marker = case
        baseline = (FIXTURES / task.fixture / provider).read_text(encoding="utf-8")
        assert "def quote(item):" in baseline or "def slugify(text):" in baseline
