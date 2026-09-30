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
from .deadline import PartialRun, RunDeadline, RunTimedOutError
from .definition import (
    AgentRole,
    SuccessCriteria,
    TaskDefinition,
    TaskError,
    TaskFamily,
)
from .handoff import (
    HandoffDirective,
    HandoffError,
    build_handoff_record,
    handoff_events,
    handoff_payload,
    record_sha256,
    verify_handoff_payload,
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
    "HandoffDirective",
    "HandoffError",
    "ImportOptions",
    "ImportedFeature",
    "ImportedTask",
    "PartialRun",
    "RunConfig",
    "RunDeadline",
    "RunResult",
    "RunTimedOutError",
    "SensitivityReport",
    "SuccessCriteria",
    "TaskDefinition",
    "TaskError",
    "TaskFamily",
    "TaskOutcome",
    "ValidationIssue",
    "ValidationReport",
    "build_handoff_record",
    "check_sensitivity",
    "decide_acceptance",
    "diverged_files",
    "evaluate_outcome",
    "execute_task",
    "handoff_events",
    "handoff_payload",
    "import_dataset",
    "import_task",
    "load_tasks",
    "record_sha256",
    "touched_paths",
    "validate_structure",
    "verify_handoff_payload",
    "workspace_digest",
]
