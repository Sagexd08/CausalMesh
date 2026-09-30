"""A generated coordination task for N agents (spec §86, scalability profile).

The four authored tasks fix the agent count at two. To ask what happens to
coordination cost beyond that, the same task shape has to exist at N = 4, 8,
16 and so on, and hand-writing sixteen agents' scripts would invite the
scripts to differ in more than N. So the task is *generated* from three
parameters and is otherwise identical at every size:

    n_agents      how many agents
    group_size    how many agents contest each shared path (the contention
                  neighbourhood)
    own_files     files in each agent's own directory

Each agent owns a directory (`src/pkg_XX/`) that nobody else touches, and
takes part in one contention group. A group shares a single registry file
(`src/shared/reg_GG.py`). The first member of a group owns it and the others
depend on it. Every member registers itself in it, and the registry must end
up listing every member. A member that knows its predecessors registered
writes all of them; one that does not writes only itself and leaves the
`sole registration` marker, which is the same last-writer-wins divergence
`concurrent_edit_collision` induces for two agents.

**What the task does and does not test.** It is scripted and deterministic,
run by the mock agent; nothing about it says how a real agent would behave.
The contention neighbourhood is `group_size`, held fixed as N grows by
default, which is a *choice about topology*: it models many agents each
working near a few others. Set `group_size = n_agents` and every agent
contests the same path, which is the dense case where interest-scoped
delivery has nothing to remove on the shared path. Both are reported by the
scalability profile so the result does not depend on the easy topology alone.

This module builds the task definition and its repository fixture. It does
not add anything to `tasks/` or `fixtures/`, so no existing experiment plan
changes: the fixture is written into a scratch directory at run time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from .definition import AgentRole, SuccessCriteria, TaskDefinition, TaskError, TaskFamily

__all__ = [
    "MAX_SCALED_AGENTS",
    "SOLE_REGISTRATION_MARKER",
    "ScaledSpec",
    "generate_scaled_task",
    "scaled_fixture_files",
    "write_scaled_fixture",
]

MAX_SCALED_AGENTS = 99
"""Agent ids are two digits (`agent_07`), which keeps ids sorted and fixed width."""

SOLE_REGISTRATION_MARKER = "# sole registration"


@dataclass(frozen=True, slots=True)
class ScaledSpec:
    """The parameters that define one scaled task."""

    n_agents: int
    group_size: int = 4
    own_files: int = 2

    def __post_init__(self) -> None:
        if not 2 <= self.n_agents <= MAX_SCALED_AGENTS:
            raise TaskError(
                f"n_agents must be between 2 and {MAX_SCALED_AGENTS}, got {self.n_agents}"
            )
        if not 2 <= self.group_size <= self.n_agents:
            raise TaskError(
                f"group_size must be between 2 and n_agents ({self.n_agents}), "
                f"got {self.group_size}; a group of one contests nothing"
            )
        if self.own_files < 1:
            raise TaskError(f"own_files must be at least 1, got {self.own_files}")

    @property
    def task_id(self) -> str:
        return f"scaled_n{self.n_agents:02d}_g{self.group_size:02d}_f{self.own_files:02d}"

    @property
    def groups(self) -> int:
        return math.ceil(self.n_agents / self.group_size)

    def agent_id(self, index: int) -> str:
        return f"agent_{index:02d}"

    def group_of(self, index: int) -> int:
        return index // self.group_size

    def members(self, group: int) -> tuple[str, ...]:
        first = group * self.group_size
        last = min(first + self.group_size, self.n_agents)
        return tuple(self.agent_id(i) for i in range(first, last))

    def own_paths(self, index: int) -> tuple[str, ...]:
        return tuple(f"src/pkg_{index:02d}/m{j}.py" for j in range(self.own_files))

    def shared_path(self, group: int) -> str:
        return f"src/shared/reg_{group:02d}.py"


def _registry_source(group: int, members: tuple[str, ...], *, sole: bool = False) -> str:
    listed = ", ".join(repr(member) for member in members)
    marker = f"  {SOLE_REGISTRATION_MARKER}" if sole else ""
    return f'"""Shared registry {group:02d}."""\n\nMEMBERS = [{listed}]{marker}\n'


def _owned_source(agent: str, index: int, *, value: int) -> str:
    return f'"""{agent} module {index}."""\n\nVALUE = {value}\n'


def generate_scaled_task(spec: ScaledSpec) -> TaskDefinition:
    """Build the validated task for `spec`.

    Deterministic: the same spec always yields a byte-identical definition,
    so `content_hash()` pins what ran.
    """
    roles: list[AgentRole] = []
    scenario: dict[str, dict[str, object]] = {}
    contested: set[str] = set()

    for group in range(spec.groups):
        if len(spec.members(group)) >= 2:
            contested.add(spec.shared_path(group))

    for index in range(spec.n_agents):
        agent = spec.agent_id(index)
        group = spec.group_of(index)
        members = spec.members(group)
        position = members.index(agent)
        shared = spec.shared_path(group)
        own = spec.own_paths(index)

        owns = set(own)
        depends_on: set[str] = set()
        if position == 0:
            owns.add(shared)
        else:
            depends_on.add(shared)

        actions: list[dict[str, object]] = []
        for j, path in enumerate(own):
            actions.append({"read": path})
            actions.append({"write": {"path": path, "content": _owned_source(agent, j, value=1)}})
        actions.append({"read": shared})
        if position == 0:
            actions.append(
                {"write": {"path": shared, "content": _registry_source(group, (agent,))}}
            )
        else:
            actions.append(
                {
                    "write": {
                        "if_informed_about": shared,
                        "path": shared,
                        "content": _registry_source(group, members[: position + 1]),
                    }
                }
            )
            actions.append(
                {
                    "write": {
                        "if_uninformed_about": shared,
                        "path": shared,
                        "content": _registry_source(group, (agent,), sole=True),
                    }
                }
            )

        roles.append(
            AgentRole(
                agent_id=agent,
                owns=frozenset(owns),
                depends_on=frozenset(depends_on),
                description=f"Owns pkg_{index:02d} and registers in {shared}.",
            )
        )
        scenario[agent] = {
            "owns": sorted(owns),
            "depends_on": sorted(depends_on),
            "actions": actions,
        }

    return TaskDefinition(
        task_id=spec.task_id,
        version="1.0.0",
        family=TaskFamily.CONCURRENT_EDIT_COLLISION,
        description=(
            f"{spec.n_agents} agents, each owning a directory of {spec.own_files} file(s), "
            f"contesting shared registries in groups of {spec.group_size}. Generated; "
            "scripted mock agents only."
        ),
        fixture=spec.task_id,
        roles=tuple(roles),
        scenario=scenario,
        success=SuccessCriteria(
            integration_test=("python", "tests/check_scaled.py"),
            divergence_file=spec.shared_path(0),
            divergence_marker=SOLE_REGISTRATION_MARKER,
        ),
        contested_paths=frozenset(contested),
    )


def _check_script(spec: ScaledSpec) -> str:
    expected = {f"reg_{group:02d}": list(spec.members(group)) for group in range(spec.groups)}
    return (
        '"""Every shared registry must list every member of its group."""\n\n'
        "import importlib\n"
        "import sys\n"
        "from pathlib import Path\n\n"
        'sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))\n\n'
        f"EXPECTED = {expected!r}\n\n"
        "failures = []\n"
        "for name, members in sorted(EXPECTED.items()):\n"
        '    found = importlib.import_module("shared." + name).MEMBERS\n'
        "    if found != members:\n"
        '        failures.append(f"{name}: expected {members}, found {found}")\n'
        "for line in failures:\n"
        "    print(line)\n"
        "sys.exit(1 if failures else 0)\n"
    )


def scaled_fixture_files(spec: ScaledSpec) -> dict[str, str]:
    """The repository every agent starts from, as relative path -> text."""
    files: dict[str, str] = {"tests/check_scaled.py": _check_script(spec)}
    for group in range(spec.groups):
        files[spec.shared_path(group)] = _registry_source(group, ())
    for index in range(spec.n_agents):
        agent = spec.agent_id(index)
        for j, path in enumerate(spec.own_paths(index)):
            files[path] = _owned_source(agent, j, value=0)
    return files


def write_scaled_fixture(spec: ScaledSpec, fixtures_root: Path) -> Path:
    """Materialise the fixture under `fixtures_root/<task_id>` and return it.

    LF newlines are written explicitly, so the fixture, and therefore every
    file digest, is the same on every platform.
    """
    root = Path(fixtures_root) / spec.task_id
    for relative, text in scaled_fixture_files(spec).items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
    return root
