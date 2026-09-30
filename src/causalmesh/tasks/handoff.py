"""The handoff record: what a successor agent inherits (`docs/backlog.md`,
"Agent handoff package on recovery").

A run is normally one set of agents from start to end. A handoff is the one
sanctioned exception: an operator relieves one agent mid-run and a different
agent takes over its seat. The successor should start from where the
predecessor stopped, not cold, so this module builds the package it starts
from:

- the task (id and content hash);
- the repository state: what changed in the predecessor's workspace since
  the run began, as digests and a unified diff;
- the test results the predecessor recorded on the chain;
- the decisions already taken about it: policy verdicts and refusals;
- what it had been told (`informed_paths`) and how much of its script is
  left, so the successor's conditional behaviour is seeded from the record
  and from nothing else.

**Deterministic and verifiable offline.** The record is a pure function of
the chain so far, the workspace contents and the operator's directive. It
holds no wall-clock time, no hostname, no absolute path and no random id, so
the same run reproduces the same record byte for byte. It goes into the
signed chain as a `HANDOFF` event whose payload carries the record and its
SHA-256, so a verifier with only the chain can recompute the digest
(`verify_handoff_payload`) without reaching any other artifact.

**This is mechanism, not policy.** The directive names who hands off to whom
and when. Nothing here decides *that* a run should be handed off; there is
no recovery policy, and none is invented. Wiring a decision engine to choose
between retrying, switching agents and escalating is the work this enables,
not work done here.

This module is at the `tasks` layer for the same import-cycle reason as
`tasks.deadline`.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from ..agents.script import AgentScript
from ..events.canonical import canonicalize
from ..events.schema import EventType
from ..isolation import Workspace

__all__ = [
    "HANDOFF_RECORD_VERSION",
    "MAX_DIFF_CHARS",
    "HandoffDirective",
    "HandoffError",
    "build_handoff_record",
    "handoff_events",
    "handoff_payload",
    "record_sha256",
    "snapshot_workspace",
    "verify_handoff_payload",
]

HANDOFF_RECORD_VERSION = 1

# The diff travels inside a signed event, so it is bounded. A diff cut short
# says so (`diff_truncated`) and the per-file digests still cover every
# change, so truncation loses readability and never the fact of a change.
MAX_DIFF_CHARS = 32_768

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

# Files a test run leaves behind. They are not the agent's work and would
# make two otherwise identical runs disagree about "what changed".
_NOISE = frozenset({"__pycache__", ".pytest_cache"})


class HandoffError(ValueError):
    """A handoff could not be requested or built as specified."""


@dataclass(frozen=True)
class HandoffDirective:
    """An operator's explicit instruction to relieve one agent for another.

    `at_turn` is the turn at whose start the handoff happens, before any
    agent acts in it. `reason` is the operator's own words, recorded
    verbatim in the signed event.

    `successor_script` is what the incoming agent will do. Left unset, the
    successor continues the predecessor's script from the action after the
    last one the predecessor took, which is the "picks up where it left off"
    case. It is a scripted mock agent either way: this is the mechanism
    exercised with a deterministic agent, and says nothing about how a
    model-backed agent would use the package.
    """

    from_agent: str
    to_agent: str
    at_turn: int
    reason: str
    successor_script: AgentScript | None = None

    def __post_init__(self) -> None:
        for name in ("from_agent", "to_agent"):
            value = getattr(self, name)
            if not isinstance(value, str) or not _IDENTIFIER.match(value):
                raise HandoffError(f"{name} must match {_IDENTIFIER.pattern!r}, got {value!r}")
        if self.from_agent == self.to_agent:
            raise HandoffError(
                f"an agent cannot be handed off to itself ({self.from_agent!r}); "
                "that would be a retry, which is a different decision"
            )
        if isinstance(self.at_turn, bool) or not isinstance(self.at_turn, int) or self.at_turn < 0:
            raise HandoffError(f"at_turn must be a non-negative int, got {self.at_turn!r}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise HandoffError(
                "a handoff needs a reason in the operator's words; an unexplained "
                "handoff is not something an audit could interpret"
            )


def _kept(path: str) -> bool:
    return _NOISE.isdisjoint(path.split("/"))


def snapshot_workspace(workspace: Workspace) -> dict[str, bytes]:
    """The workspace's files as they are now, keyed by relative path.

    Taken once, when the run starts, so a later diff is measured against what
    the agent was given rather than against a fixture directory that may have
    been laid out differently.
    """
    return {
        relative: workspace.resolve(relative).read_bytes()
        for relative in workspace.list_files()
        if _kept(relative)
    }


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_state(baseline: Mapping[str, bytes], workspace: Workspace) -> dict[str, Any]:
    current = snapshot_workspace(workspace)
    changed: list[dict[str, Any]] = []
    diff_parts: list[str] = []

    for path in sorted(set(baseline) | set(current)):
        before = baseline.get(path)
        after = current.get(path)
        if before == after:
            continue
        status = "added" if before is None else "deleted" if after is None else "modified"
        entry: dict[str, Any] = {
            "after_sha256": None if after is None else _sha(after),
            "before_sha256": None if before is None else _sha(before),
            "path": path,
            "status": status,
        }
        try:
            old_text = "" if before is None else before.decode("utf-8")
            new_text = "" if after is None else after.decode("utf-8")
        except UnicodeDecodeError:
            entry["binary"] = True
            changed.append(entry)
            continue
        changed.append(entry)
        diff_parts.extend(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"a/{path}" if before is not None else "/dev/null",
                tofile=f"b/{path}" if after is not None else "/dev/null",
            )
        )

    diff = "".join(diff_parts)
    truncated = len(diff) > MAX_DIFF_CHARS
    return {
        "changed": changed,
        "diff": diff[:MAX_DIFF_CHARS],
        "diff_truncated": truncated,
        "digests": {path: _sha(data) for path, data in sorted(current.items())},
    }


def _test_results(records: Iterable[Mapping[str, Any]], agent_id: str) -> list[dict[str, Any]]:
    """The predecessor's recorded test runs, read from the chain.

    Read from the signed events rather than from the agent's own account:
    what the predecessor says it ran and what the chain says it ran are not
    the same evidence, and the chain is the one a verifier can check.
    """
    results: list[dict[str, Any]] = []
    for record in records:
        event = record["event"]
        if event["event_type"] != str(EventType.TEST):
            continue
        if event["identity"]["agent_id"] != agent_id:
            continue
        payload = event["payload"]
        results.append(
            {
                "command": list(payload.get("command", ())),
                "event_id": event["event_id"],
                "exit_code": payload.get("exit_code"),
                "sequence": event["sequence"],
                "timed_out": payload.get("timed_out"),
            }
        )
    return results


def _refusals(records: Iterable[Mapping[str, Any]], agent_id: str) -> list[dict[str, Any]]:
    refusals: list[dict[str, Any]] = []
    for record in records:
        event = record["event"]
        payload = event["payload"]
        if event["event_type"] != str(EventType.FAILURE):
            continue
        if event["identity"]["agent_id"] != agent_id or payload.get("outcome") != "denied":
            continue
        refusals.append(
            {
                "blocked_path": payload.get("blocked_path"),
                "event_id": event["event_id"],
                "reason": payload.get("reason"),
                "rule": payload.get("rule"),
                "tool": payload.get("tool"),
            }
        )
    return refusals


def build_handoff_record(
    *,
    run_id: str,
    task_id: str,
    task_hash: str,
    directive: HandoffDirective,
    records: list[dict[str, Any]],
    head_hash: str | None,
    baseline: Mapping[str, bytes],
    workspace: Workspace,
    informed_paths: Iterable[str],
    remaining_actions: int,
    predecessor_turns: int,
    predecessor_finished: bool,
    predecessor_crashed: bool,
    policy_verdicts: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Assemble the package the successor starts from.

    `policy_verdicts` is whatever the installed gate has decided so far, or
    empty when the gate keeps no verdict list (the arms' own gates do not).
    Empty means "this gate recorded no verdicts", and the record says which
    gate facts it does hold rather than implying a clean history.
    """
    return {
        "chain_anchor": {"events": len(records), "head_hash": head_hash},
        "from_agent": directive.from_agent,
        "informed_paths": sorted(informed_paths),
        "predecessor": {
            "crashed": predecessor_crashed,
            "finished": predecessor_finished,
            "remaining_actions": remaining_actions,
            "turns": predecessor_turns,
        },
        "prior_decisions": {
            "policy_verdicts": [dict(v) for v in policy_verdicts],
            "refusals": _refusals(records, directive.from_agent),
        },
        "reason": directive.reason,
        "record_version": HANDOFF_RECORD_VERSION,
        "repo_state": _repo_state(baseline, workspace),
        "run_id": run_id,
        "at_turn": directive.at_turn,
        "task": {"task_id": task_id, "task_hash": task_hash},
        "test_results": _test_results(records, directive.from_agent),
        "to_agent": directive.to_agent,
    }


def record_sha256(record: Mapping[str, Any]) -> str:
    """The digest of a record's canonical bytes."""
    return hashlib.sha256(canonicalize(dict(record))).hexdigest()


def handoff_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """The `HANDOFF` event payload: the record and its own digest."""
    return {"record": dict(record), "record_sha256": record_sha256(record)}


def verify_handoff_payload(payload: Mapping[str, Any]) -> bool:
    """Whether a `HANDOFF` payload's digest matches its record.

    Needs nothing but the payload, so it runs on a chain exported from a run
    on another machine. It checks the record is the one that was signed, not
    that the record is a truthful account: whether the diff matches a
    workspace is answerable only while the workspace still exists.
    """
    record = payload.get("record")
    digest = payload.get("record_sha256")
    if not isinstance(record, dict) or not isinstance(digest, str):
        return False
    return record_sha256(record) == digest


def handoff_events(records: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The `HANDOFF` events of a chain, in order, as their payloads."""
    return [
        dict(record["event"]["payload"])
        for record in records
        if record["event"]["event_type"] == str(EventType.HANDOFF)
    ]
