"""The handoff package: what a second agent inherits (backlog: "Agent handoff
package on recovery").

When a run continues under a different agent, the newcomer should start from
where the first agent stopped rather than cold. The backlog names five things
it needs: the task, the repository state, the diff so far, the test results
and the decisions already taken. This module is that record shape and
nothing else. It has no producer (nothing builds one from a live run), no
consumer (no agent is handed one) and no chain event; those belong to the
multi-agent orchestration that does not exist yet.

Three rules shape the record, each taken from AGENTS.md:

**An absent field is unknown, never empty.** `diff` and `test_results` are
`None` when nobody computed them and `()` when they were computed and there
was nothing to report. A package that says "no test failures" because it
never ran the tests is the confident zero this project has already shipped
once. Within a test result, `exit_code` and `passed` are likewise `None` when
unknown.

**Nothing non-reproducible.** There is no timestamp, hostname or absolute
path in the record, and paths are validated as repository-relative, so the
same handoff built twice serialises to the same bytes and has the same
`digest()`. That is what lets a later chain event commit to a package by
hash without the package perturbing a bit-reproducible chain.

**Deterministic serialisation.** `to_dict` is plain JSON types; `to_json`
and `digest` go through the project's canonical JSON, the same one the hash
chain and signatures consume, so there is exactly one definition of "the
bytes of this record".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, ClassVar

from ..events.canonical import canonical_json

__all__ = [
    "HANDOFF_SCHEMA_VERSION",
    "DiffEntry",
    "HandoffError",
    "HandoffPackage",
    "PriorDecision",
    "TestResult",
]

HANDOFF_SCHEMA_VERSION = 1

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CHANGES = frozenset({"added", "modified", "deleted"})


class HandoffError(ValueError):
    """A handoff package or one of its parts is malformed."""


def _require_relative(path: str, *, what: str) -> str:
    """Repository-relative, forward-slash, no traversal.

    An absolute path would put the machine's layout into a record meant to be
    byte-identical across machines.
    """
    if not isinstance(path, str) or not path:
        raise HandoffError(f"{what} must be a non-empty string, got {path!r}")
    if path.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", path) or "\\" in path:
        raise HandoffError(
            f"{what} {path!r} is not repository-relative; handoff records carry no absolute "
            "or platform-specific paths"
        )
    if any(part in ("..", "") for part in path.split("/")):
        raise HandoffError(f"{what} {path!r} contains an empty or '..' segment")
    return path


def _require_digest(value: str | None, *, what: str, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        raise HandoffError(f"{what} is required")
    if not isinstance(value, str) or not _SHA256.match(value):
        raise HandoffError(f"{what} must be a lowercase sha256 hex digest, got {value!r}")
    return value


def _check_keys(data: dict[str, Any], *, allowed: set[str], required: set[str], what: str) -> None:
    if not isinstance(data, dict):
        raise HandoffError(f"{what} must be an object, got {type(data).__name__}")
    unknown = set(data) - allowed
    if unknown:
        raise HandoffError(f"{what} has unknown field(s) {sorted(unknown)}")
    missing = required - set(data)
    if missing:
        raise HandoffError(f"{what} is missing field(s) {sorted(missing)}")


@dataclass(frozen=True)
class DiffEntry:
    """One file's change since the repository state the run started from.

    Digests, not contents, are required; `patch` is optional text for when the
    receiving agent should see the change rather than only know of it. A
    `added` entry has no `before_digest`, a `deleted` entry no `after_digest`,
    and the constructor refuses the contradiction.
    """

    path: str
    change: str
    before_digest: str | None = None
    after_digest: str | None = None
    patch: str | None = None

    def __post_init__(self) -> None:
        _require_relative(self.path, what="diff path")
        if self.change not in _CHANGES:
            raise HandoffError(f"diff change {self.change!r} is not one of {sorted(_CHANGES)}")
        _require_digest(self.before_digest, what="before_digest", optional=True)
        _require_digest(self.after_digest, what="after_digest", optional=True)
        if self.change == "added" and self.before_digest is not None:
            raise HandoffError(f"{self.path}: an added file has no before_digest")
        if self.change == "deleted" and self.after_digest is not None:
            raise HandoffError(f"{self.path}: a deleted file has no after_digest")
        if self.change != "added" and self.before_digest is None:
            raise HandoffError(f"{self.path}: a {self.change} file needs its before_digest")
        if self.change != "deleted" and self.after_digest is None:
            raise HandoffError(f"{self.path}: a {self.change} file needs its after_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "after_digest": self.after_digest,
            "before_digest": self.before_digest,
            "change": self.change,
            "patch": self.patch,
            "path": self.path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffEntry:
        keys = {"after_digest", "before_digest", "change", "patch", "path"}
        _check_keys(data, allowed=keys, required=keys, what="diff entry")
        return cls(
            path=data["path"],
            change=data["change"],
            before_digest=data["before_digest"],
            after_digest=data["after_digest"],
            patch=data["patch"],
        )


@dataclass(frozen=True)
class TestResult:
    """One test command's result, with unknown kept distinct from failed.

    `exit_code` is `None` when the command could not be run or timed out, and
    `passed` follows it: `None` unless an exit code decided it. `output_digest`
    points at captured output without embedding it.
    """

    __test__: ClassVar[bool] = False  # not a pytest test class, despite the name

    command: tuple[str, ...]
    exit_code: int | None = None
    passed: bool | None = None
    output_digest: str | None = None

    def __post_init__(self) -> None:
        if not self.command or not all(isinstance(part, str) for part in self.command):
            raise HandoffError("a test result needs a command of one or more strings")
        if self.exit_code is not None and (
            isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int)
        ):
            raise HandoffError(f"exit_code must be an int or None, got {self.exit_code!r}")
        if self.passed is not None and self.exit_code is None:
            raise HandoffError("passed is set but exit_code is unknown; it cannot be decided")
        if self.passed is not None and self.passed != (self.exit_code == 0):
            raise HandoffError(f"passed={self.passed} contradicts exit_code={self.exit_code}")
        _require_digest(self.output_digest, what="output_digest", optional=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "output_digest": self.output_digest,
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestResult:
        keys = {"command", "exit_code", "output_digest", "passed"}
        _check_keys(data, allowed=keys, required=keys, what="test result")
        command = data["command"]
        if not isinstance(command, list):
            raise HandoffError("test result command must be a list")
        return cls(
            command=tuple(command),
            exit_code=data["exit_code"],
            passed=data["passed"],
            output_digest=data["output_digest"],
        )


@dataclass(frozen=True)
class PriorDecision:
    """A decision already taken on this run, by reference to the chain.

    `event_id` points at the signed event that recorded it (a policy verdict,
    an acceptance decision, a checkpoint). The summary is for the reader's
    convenience; the event is the authority, which is why it is required.
    """

    event_id: str
    kind: str
    summary: str

    def __post_init__(self) -> None:
        for name in ("event_id", "kind", "summary"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise HandoffError(f"prior decision {name} must be a non-empty string")

    def to_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "kind": self.kind, "summary": self.summary}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PriorDecision:
        keys = {"event_id", "kind", "summary"}
        _check_keys(data, allowed=keys, required=keys, what="prior decision")
        return cls(event_id=data["event_id"], kind=data["kind"], summary=data["summary"])


@dataclass(frozen=True)
class HandoffPackage:
    """Everything a continuing agent inherits from the one that stopped.

    `to_agent` is `None` until a recovery decision has picked a successor:
    unknown, not "nobody". `repository_digest` is one hash over the whole
    repository state at handoff, for checking the newcomer starts from the
    state the package describes; `diff` says how that state differs from where
    the run began. Both `diff` and `test_results` distinguish "not computed"
    (`None`) from "computed, empty" (`()`).
    """

    run_id: str
    task_id: str
    task_hash: str
    from_agent: str
    repository_digest: str
    to_agent: str | None = None
    objective: str | None = None
    diff: tuple[DiffEntry, ...] | None = None
    test_results: tuple[TestResult, ...] | None = None
    prior_decisions: tuple[PriorDecision, ...] = ()
    schema_version: int = HANDOFF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("run_id", "task_id", "from_agent"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise HandoffError(f"{name} must be a non-empty string")
        if self.to_agent is not None and (not self.to_agent or self.to_agent == self.from_agent):
            raise HandoffError(
                "to_agent must be a different, non-empty agent than from_agent "
                f"(got {self.to_agent!r} for {self.from_agent!r})"
            )
        _require_digest(self.task_hash, what="task_hash")
        _require_digest(self.repository_digest, what="repository_digest")
        if self.schema_version != HANDOFF_SCHEMA_VERSION:
            raise HandoffError(
                f"unsupported handoff schema_version {self.schema_version!r}; "
                f"this build reads {HANDOFF_SCHEMA_VERSION}"
            )
        if self.diff is not None:
            paths = [entry.path for entry in self.diff]
            if len(paths) != len(set(paths)):
                raise HandoffError("diff names the same path twice")
            if paths != sorted(paths):
                raise HandoffError(
                    "diff entries must be sorted by path so the same change serialises one way"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "diff": None if self.diff is None else [entry.to_dict() for entry in self.diff],
            "from_agent": self.from_agent,
            "objective": self.objective,
            "prior_decisions": [decision.to_dict() for decision in self.prior_decisions],
            "repository_digest": self.repository_digest,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "task_hash": self.task_hash,
            "task_id": self.task_id,
            "test_results": (
                None if self.test_results is None else [t.to_dict() for t in self.test_results]
            ),
            "to_agent": self.to_agent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HandoffPackage:
        keys = {
            "diff",
            "from_agent",
            "objective",
            "prior_decisions",
            "repository_digest",
            "run_id",
            "schema_version",
            "task_hash",
            "task_id",
            "test_results",
            "to_agent",
        }
        # Every field is required on the wire, including the nullable ones: a
        # record that omits `test_results` must not be readable as "unknown".
        _check_keys(data, allowed=keys, required=keys, what="handoff package")
        diff = data["diff"]
        tests = data["test_results"]
        decisions = data["prior_decisions"]
        if diff is not None and not isinstance(diff, list):
            raise HandoffError("handoff diff must be a list or null")
        if tests is not None and not isinstance(tests, list):
            raise HandoffError("handoff test_results must be a list or null")
        if not isinstance(decisions, list):
            raise HandoffError("handoff prior_decisions must be a list")
        return cls(
            run_id=data["run_id"],
            task_id=data["task_id"],
            task_hash=data["task_hash"],
            from_agent=data["from_agent"],
            repository_digest=data["repository_digest"],
            to_agent=data["to_agent"],
            objective=data["objective"],
            diff=None if diff is None else tuple(DiffEntry.from_dict(e) for e in diff),
            test_results=None if tests is None else tuple(TestResult.from_dict(t) for t in tests),
            prior_decisions=tuple(PriorDecision.from_dict(d) for d in decisions),
            schema_version=data["schema_version"],
        )

    def to_json(self) -> str:
        """The canonical JSON text: sorted keys, no whitespace, stable bytes."""
        return canonical_json(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> HandoffPackage:
        import json

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HandoffError(f"handoff package is not valid JSON: {exc}") from exc
        return cls.from_dict(data)

    def digest(self) -> str:
        """SHA-256 of the canonical JSON: how a chain event would commit to this."""
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()
