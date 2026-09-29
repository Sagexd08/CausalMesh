"""Declarative tasks: definition, validation and outcome (spec §35 to §38).

Tasks are data, not code. A task that could execute arbitrary Python would
make "the same task" unverifiable across machines, and the configuration
hash (§33) would no longer pin what actually ran.
"""

from __future__ import annotations

from .cooperbench import (
    CooperBenchImportError,
    ImportedFeature,
    ImportedTask,
    ImportOptions,
    import_dataset,
    import_task,
    touched_paths,
)
from .definition import (
    AgentRole,
    SuccessCriteria,
    TaskDefinition,
    TaskError,
    TaskFamily,
)
from .outcome import (
    AcceptanceDecision,
    AcceptanceVerdict,
    TaskOutcome,
    decide_acceptance,
    diverged_files,
    evaluate_outcome,
    workspace_digest,
)
from .runner import RunConfig, RunResult, execute_task
from .validation import (
    SensitivityReport,
    ValidationIssue,
    ValidationReport,
    check_sensitivity,
    load_tasks,
    validate_structure,
)

__all__ = [
    "AcceptanceDecision",
    "AcceptanceVerdict",
    "AgentRole",
    "CooperBenchImportError",
    "ImportOptions",
    "ImportedFeature",
    "ImportedTask",
    "RunConfig",
    "RunResult",
    "SensitivityReport",
    "SuccessCriteria",
    "TaskDefinition",
    "TaskError",
    "TaskFamily",
    "TaskOutcome",
    "ValidationIssue",
    "ValidationReport",
    "check_sensitivity",
    "decide_acceptance",
    "diverged_files",
    "evaluate_outcome",
    "execute_task",
    "import_dataset",
    "import_task",
    "load_tasks",
    "touched_paths",
    "validate_structure",
    "workspace_digest",
]
