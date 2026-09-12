"""Task validation and the coordination-sensitivity gate (spec §36, §37).

Two levels, and the distinction matters.

**Structural validation (§36)** checks that a task is well-formed: the
fixture exists, roles and scenario agree, the declared tests are runnable,
the divergence check names a real file. This is cheap and runs on every
task.

**The quality gate (§37)** is the demanding one:

    A task must demonstrate empirically that the coordination dependency
    actually exists. Do not assume a task is coordination-sensitive merely
    because its YAML says it is.

The gate answers that by *running the task* under C0 and C2 with the mock
agents and comparing outcomes. A task whose success is identical in both
arms cannot distinguish them: whatever else it measures, it contributes
nothing to the contrasts the experiment is built on, and including it would
dilute the effect the analysis is trying to detect.

C2 rather than C3 is the comparison arm. C3 adds enforcement on top of
information, so a C0-versus-C3 difference could come from either factor;
C0 versus C2 isolates information alone, which is the dependency §37 asks
about.

This is deliberately expensive and deliberately not optional. A benchmark
of tasks that merely claim to be coordination-sensitive would produce a
null result that says nothing about coordination.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agents.script import ActionKind, Scenario, ScriptError
from .definition import TaskDefinition, TaskError

__all__ = [
    "SensitivityReport",
    "ValidationIssue",
    "ValidationReport",
    "check_sensitivity",
    "validate_structure",
]


# Action kinds that change a file. Shared with the scenario's own
# contention analysis so the two cannot drift apart.
_MUTATING_KINDS = frozenset(
    {
        ActionKind.WRITE,
        ActionKind.CREATE,
        ActionKind.MODIFY,
        ActionKind.DELETE,
        ActionKind.RENAME,
    }
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One problem with a task, located and explained."""

    severity: str  # "error" or "warning"
    code: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail, "severity": self.severity}


@dataclass
class ValidationReport:
    """The outcome of validating one task.

    Warnings and errors are kept apart: an error means the task must not
    run, a warning means it may but something is worth knowing. Collapsing
    them would either block valid tasks or admit broken ones.
    """

    task_id: str
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def valid(self) -> bool:
        return not self.errors

    def error(self, code: str, detail: str) -> None:
        self.issues.append(ValidationIssue("error", code, detail))

    def warn(self, code: str, detail: str) -> None:
        self.issues.append(ValidationIssue("warning", code, detail))

    def to_dict(self) -> dict[str, Any]:
        return {
            "errors": len(self.errors),
            "issues": [issue.to_dict() for issue in self.issues],
            "task_id": self.task_id,
            "valid": self.valid,
            "warnings": len(self.warnings),
        }

    def summary(self) -> str:
        if self.valid and not self.warnings:
            return f"{self.task_id}: VALID"
        if self.valid:
            return f"{self.task_id}: VALID ({len(self.warnings)} warning(s))"
        return f"{self.task_id}: INVALID ({len(self.errors)} error(s))"


def validate_structure(
    task: TaskDefinition, *, fixtures_root: Path | None = None
) -> ValidationReport:
    """Check a task is well-formed (§36).

    Structural only: it does not run the task. Whether the coordination
    dependency actually exists is the quality gate's question, and it costs
    real execution to answer.
    """
    report = ValidationReport(task_id=task.task_id)

    # -- fixture ----------------------------------------------------------
    if fixtures_root is not None:
        fixture_path = Path(fixtures_root) / task.fixture
        if not fixture_path.is_dir():
            report.error(
                "fixture_missing",
                f"fixture {task.fixture!r} not found at {fixture_path}; "
                "a task cannot run without its repository",
            )
        elif not any(fixture_path.rglob("*")):
            report.error("fixture_empty", f"fixture {task.fixture!r} contains no files")

    # -- scenario ---------------------------------------------------------
    try:
        scenario = Scenario.from_dict(task.scenario)
    except ScriptError as exc:
        report.error("scenario_invalid", str(exc))
        return report

    # -- roles versus behaviour -------------------------------------------
    for role in task.roles:
        script = scenario.agents.get(role.agent_id)
        if script is None:
            report.error("role_unscripted", f"role {role.agent_id!r} has no scenario")
            continue
        if not script.actions:
            report.error(
                "role_inactive",
                f"role {role.agent_id!r} has an empty action list and cannot "
                "contribute to the task",
            )

        touched = script.paths_touched()
        # A declared dependency the agent never reads is a documentation
        # error that would mislead the relevance scorer into ranking
        # irrelevant events highly.
        unused = role.depends_on - touched
        if unused:
            report.warn(
                "dependency_untouched",
                f"role {role.agent_id!r} declares dependencies it never touches: "
                f"{sorted(unused)}",
            )

    # -- coordination structure -------------------------------------------
    #
    # A task is coordination-sensitive when one agent's work can invalidate
    # another's. There are two distinct shapes, and requiring the first
    # would wrongly reject the second:
    #
    #   contention   two agents write the same path
    #   dependency   agent A writes a path agent B declares a dependency on
    #
    # The dependency shape is the schema/handler family (§35) and it was
    # verified empirically to separate the arms with no contested path at
    # all: C0 fails, C1/C2/C3 succeed. Insisting on contention here would
    # have rejected a task that demonstrably works.
    observed_contention = scenario.contested_paths()

    writers: dict[str, set[str]] = {}
    for script in scenario.agents.values():
        for action in script.actions:
            if action.kind in _MUTATING_KINDS and action.path:
                writers.setdefault(action.path, set()).add(script.agent_id)

    cross_dependencies = {
        (role.agent_id, path)
        for role in task.roles
        for path in role.depends_on
        if writers.get(path, set()) - {role.agent_id}
    }

    if not observed_contention and not cross_dependencies:
        report.error(
            "no_coordination_dependency",
            "no path is written by more than one agent, and no agent depends "
            "on a path another agent writes; nothing one agent does can "
            "invalidate another's work, so this task cannot distinguish the "
            "arms and the contrasts would measure nothing",
        )

    if task.contested_paths and observed_contention != task.contested_paths:
        # The declaration is a claim about the task; if the scenario
        # disagrees, one of them is wrong and the run would be mislabelled.
        report.error(
            "contention_mismatch",
            f"task declares contested paths {sorted(task.contested_paths)} but the "
            f"scenario actually contests {sorted(observed_contention)}",
        )

    # -- success criteria --------------------------------------------------
    if not task.success.integration_test:
        report.error(
            "no_integration_test",
            "success must be decided automatically (§38); an empty test command "
            "would leave the outcome to judgement",
        )

    marker, divergence_file = task.success.divergence_marker, task.success.divergence_file
    if bool(marker) != bool(divergence_file):
        report.error(
            "incomplete_divergence_check",
            "divergence_marker and divergence_file must be given together; "
            "one without the other cannot be evaluated",
        )
    if divergence_file:
        # The divergence file must be *reachable* by the scenario — some
        # agent has to write it, or the marker can never change and the
        # check is vacuous.
        #
        # It need not be a contested path. The two coordination defects have
        # different shapes: a conflicting write happens on a path two agents
        # both write, while a stale dependency shows up in a file only one
        # agent writes, invalidated by a peer's write *elsewhere*. Requiring
        # contention here would reject every stale-dependency task, which is
        # the family the schema/handler tasks belong to (§35).
        writers = {
            script.agent_id
            for script in scenario.agents.values()
            for action in script.actions
            if action.path == divergence_file and action.kind in _MUTATING_KINDS
        }
        if not writers:
            report.error(
                "divergence_unreachable",
                f"divergence is checked in {divergence_file!r}, but no agent ever "
                "writes it, so the marker can never change and the check is vacuous",
            )

    return report


@dataclass
class SensitivityReport:
    """The result of the §37 quality gate.

    `sensitive` is the gate's verdict. The counts behind it are retained so
    a rejected task can be diagnosed rather than merely refused — and so a
    borderline task's evidence is inspectable rather than reduced to a
    boolean.
    """

    task_id: str
    isolated_successes: int
    informed_successes: int
    repetitions: int
    isolated_divergences: int = 0
    informed_divergences: int = 0
    detail: str = ""

    @property
    def sensitive(self) -> bool:
        """Whether the arms actually differ on this task.

        The criterion is that the informed arm succeeds strictly more often
        than the isolated one. Equality means the task cannot distinguish
        them; the *reverse* would be a genuine finding but not one that
        makes the task usable as a coordination benchmark, so it fails the
        gate too and the detail says which case occurred.
        """
        return self.informed_successes > self.isolated_successes

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "informed_divergences": self.informed_divergences,
            "informed_successes": self.informed_successes,
            "isolated_divergences": self.isolated_divergences,
            "isolated_successes": self.isolated_successes,
            "repetitions": self.repetitions,
            "sensitive": self.sensitive,
            "task_id": self.task_id,
        }

    def summary(self) -> str:
        verdict = "SENSITIVE" if self.sensitive else "NOT SENSITIVE"
        return (
            f"{self.task_id}: {verdict} — "
            f"C0 {self.isolated_successes}/{self.repetitions}, "
            f"C2 {self.informed_successes}/{self.repetitions}"
        )


async def check_sensitivity(
    task: TaskDefinition,
    *,
    workspace_root: Path,
    fixtures_root: Path,
    master_seed: bytes,
    repetitions: int = 1,
) -> SensitivityReport:
    """The §37 quality gate: run the task and prove the arms differ.

    Runs the task under C0 (no information, no enforcement) and C2
    (information, no enforcement) and compares outcomes. A task whose
    success is identical in both cannot distinguish them, and including it
    would dilute the effect the analysis is trying to detect.

    C2 rather than C3 is the comparison arm. C3 adds enforcement on top of
    information, so a C0-versus-C3 difference could come from either
    factor; C0 versus C2 isolates information alone, which is the
    dependency §37 asks about.

    Deliberately expensive and deliberately not optional. A benchmark of
    tasks that merely claim to be coordination-sensitive would produce a
    null result that says nothing about coordination.

    Imported here rather than at module scope: the runner imports the whole
    agent and relay stack, and the validator must stay importable by the
    CLI for structural checks without dragging the runtime in.
    """
    from .runner import RunConfig, execute_task

    isolated_successes = 0
    informed_successes = 0
    isolated_divergences = 0
    informed_divergences = 0

    for repetition in range(repetitions):
        for arm, is_informed in (("C0", False), ("C2", True)):
            run_id = f"gate_{task.task_id}_{arm}_{repetition}"
            result = await execute_task(
                task,
                RunConfig(
                    experiment_id=f"gate_{task.task_id}",
                    run_id=run_id,
                    arm=arm,
                    master_seed=master_seed,
                ),
                workspace_root=Path(workspace_root) / run_id,
                fixtures_root=fixtures_root,
            )
            if is_informed:
                informed_successes += int(result.succeeded)
                informed_divergences += int(not result.outcome.divergence_absent)
            else:
                isolated_successes += int(result.succeeded)
                isolated_divergences += int(not result.outcome.divergence_absent)

    if informed_successes > isolated_successes:
        detail = (
            "information changes the outcome: the informed arm succeeds more "
            "often than the isolated one"
        )
    elif informed_successes == isolated_successes:
        detail = (
            "the arms are indistinguishable on this task; it contributes "
            "nothing to the contrasts and would dilute the measured effect"
        )
    else:
        detail = (
            "the isolated arm outperforms the informed one, which is a finding "
            "but not one that makes this task usable as a coordination benchmark"
        )

    return SensitivityReport(
        task_id=task.task_id,
        isolated_successes=isolated_successes,
        informed_successes=informed_successes,
        repetitions=repetitions,
        isolated_divergences=isolated_divergences,
        informed_divergences=informed_divergences,
        detail=detail,
    )


def load_tasks(directory: Path) -> list[TaskDefinition]:
    """Load every task definition in a directory.

    A malformed file raises rather than being skipped: silently omitting a
    task would change the benchmark's composition without anyone noticing,
    and §33 requires the task suite to be pinned by hash.
    """
    directory = Path(directory)
    if not directory.is_dir():
        raise TaskError(f"task directory {directory} does not exist")

    tasks = []
    for path in sorted(directory.glob("*.yaml")):
        tasks.append(TaskDefinition.from_yaml(path))

    ids = [task.task_id for task in tasks]
    duplicates = {task_id for task_id in ids if ids.count(task_id) > 1}
    if duplicates:
        raise TaskError(f"duplicate task ids in {directory}: {sorted(duplicates)}")
    return tasks
