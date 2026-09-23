"""Declarative task definitions (spec §35, §36).

A task bundles everything a run needs to be reproducible:

    repository fixture      agent assignments and roles
    dependency graph        success criteria
    integration tests       divergence checks
    task version

Tasks are data, not code. A task that could execute arbitrary Python would
make "the same task" unverifiable across machines, and the configuration
hash (§33) would no longer pin what actually ran.

Validation is strict and happens before any run (§36): an invalid task never
enters the experiment. The alternative — discovering a malformed dependency
graph halfway through a 1920-run collection — wastes the collection and
produces data that cannot be pooled.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..events.canonical import canonicalize

__all__ = [
    "AgentRole",
    "SuccessCriteria",
    "TaskDefinition",
    "TaskError",
    "TaskFamily",
]


class TaskError(ValueError):
    """Raised when a task definition is invalid."""


class TaskFamily:
    """The four families §35 names.

    A plain namespace rather than an enum: families are a descriptive
    grouping used for reporting task composition (§69), not a switch that
    changes behaviour. Making them an enum would invite code that branches
    on family, which would let two families differ in more than their task
    content.
    """

    SCHEMA_HANDLER = "schema_handler"
    INTERFACE_CONSUMER = "interface_consumer"
    SHARED_UTILITY_REFACTOR = "shared_utility_refactor"
    CONCURRENT_EDIT_COLLISION = "concurrent_edit_collision"

    ALL = frozenset(
        {
            SCHEMA_HANDLER,
            INTERFACE_CONSUMER,
            SHARED_UTILITY_REFACTOR,
            CONCURRENT_EDIT_COLLISION,
        }
    )


@dataclass(frozen=True, slots=True)
class AgentRole:
    """One agent's assignment within a task (§35).

    `owns` and `depends_on` are the declared interests the relevance scorer
    consumes (§17). Declaring them here rather than inferring them from
    behaviour is what keeps the information an agent receives independent of
    what it has already done.
    """

    agent_id: str
    owns: frozenset[str] = frozenset()
    depends_on: frozenset[str] = frozenset()
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "depends_on": sorted(self.depends_on),
            "description": self.description,
            "owns": sorted(self.owns),
        }


@dataclass(frozen=True, slots=True)
class SuccessCriteria:
    """How a run is judged (§38).

    Success requires integration tests to pass **and** the induced
    divergence to be absent. Both, not either: a run whose tests pass while
    the divergence remains has not actually resolved the coordination
    problem, it has only failed to notice it.

    There is deliberately no subjective field. §38 forbids subjective labels
    for the primary outcome, so success is computed from an exit code and a
    file check, never from anyone's judgement.
    """

    integration_test: tuple[str, ...] = ("python", "-m", "pytest", "-q")
    divergence_file: str | None = None
    divergence_marker: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "divergence_file": self.divergence_file,
            "divergence_marker": self.divergence_marker,
            "integration_test": list(self.integration_test),
        }


@dataclass(frozen=True)
class TaskDefinition:
    """A complete, validated task."""

    task_id: str
    version: str
    family: str
    description: str
    fixture: str
    roles: tuple[AgentRole, ...]
    scenario: dict[str, Any]
    success: SuccessCriteria = field(default_factory=SuccessCriteria)
    contested_paths: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.task_id or not self.task_id.replace("_", "").replace("-", "").isalnum():
            raise TaskError(
                f"task_id must be alphanumeric with underscores or hyphens, got {self.task_id!r}"
            )
        if not self.version:
            raise TaskError(f"{self.task_id}: version is required so results are attributable")
        if self.family not in TaskFamily.ALL:
            raise TaskError(
                f"{self.task_id}: unknown family {self.family!r}; "
                f"expected one of {sorted(TaskFamily.ALL)}"
            )
        if len(self.roles) < 2:
            raise TaskError(
                f"{self.task_id}: a coordination task needs at least two agents; "
                f"got {len(self.roles)}"
            )

        agent_ids = [role.agent_id for role in self.roles]
        if len(set(agent_ids)) != len(agent_ids):
            raise TaskError(f"{self.task_id}: duplicate agent ids in roles: {agent_ids}")

        scripted = set(self.scenario)
        declared = set(agent_ids)
        if scripted != declared:
            raise TaskError(
                f"{self.task_id}: roles and scenario disagree about the agents. "
                f"Roles declare {sorted(declared)}, the scenario scripts "
                f"{sorted(scripted)}. A mismatch means some agent runs without a "
                "declared role, or a declared role never acts."
            )

    @property
    def agent_ids(self) -> tuple[str, ...]:
        return tuple(role.agent_id for role in self.roles)

    def role_for(self, agent_id: str) -> AgentRole:
        for role in self.roles:
            if role.agent_id == agent_id:
                return role
        raise TaskError(f"{self.task_id}: no role for agent {agent_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "contested_paths": sorted(self.contested_paths),
            "description": self.description,
            "family": self.family,
            "fixture": self.fixture,
            "roles": [role.to_dict() for role in self.roles],
            "scenario": self.scenario,
            "success": self.success.to_dict(),
            "task_id": self.task_id,
            "version": self.version,
        }

    def content_hash(self) -> str:
        """A stable digest of everything that defines this task.

        Recorded on every run so two runs can be shown to have used the same
        task, and so a silently edited task is detectable rather than
        producing results that are pooled with incompatible ones (§33, §43).
        """
        return hashlib.sha256(canonicalize(self.to_dict())).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskDefinition:
        if not isinstance(data, dict):
            raise TaskError(f"a task must be a mapping, got {type(data).__name__}")

        missing = {"task_id", "version", "family", "fixture", "roles", "scenario"} - set(data)
        if missing:
            raise TaskError(f"task is missing required field(s): {sorted(missing)}")

        raw_roles = data["roles"]
        if not isinstance(raw_roles, list):
            raise TaskError("roles must be a list")

        roles = []
        for index, raw in enumerate(raw_roles):
            if not isinstance(raw, dict) or "agent_id" not in raw:
                raise TaskError(f"roles[{index}]: needs at least an agent_id")
            roles.append(
                AgentRole(
                    agent_id=raw["agent_id"],
                    owns=frozenset(raw.get("owns", ())),
                    depends_on=frozenset(raw.get("depends_on", ())),
                    description=raw.get("description", ""),
                )
            )

        raw_success = data.get("success", {})
        success = SuccessCriteria(
            integration_test=tuple(
                raw_success.get("integration_test", ("python", "-m", "pytest", "-q"))
            ),
            divergence_file=raw_success.get("divergence_file"),
            divergence_marker=raw_success.get("divergence_marker"),
        )

        return cls(
            task_id=data["task_id"],
            version=str(data["version"]),
            family=data["family"],
            description=data.get("description", ""),
            fixture=data["fixture"],
            roles=tuple(roles),
            scenario=data["scenario"],
            success=success,
            contested_paths=frozenset(data.get("contested_paths", ())),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> TaskDefinition:
        import yaml

        path = Path(path)
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise TaskError(f"{path}: could not parse YAML: {exc}") from exc
        if loaded is None:
            raise TaskError(f"{path}: file is empty")
        return cls.from_dict(loaded)
