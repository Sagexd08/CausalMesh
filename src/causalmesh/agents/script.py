"""Declarative scripts for the mock agent (spec §9).

§9 gives the shape of a scenario:

```yaml
agent_a:
  actions:
    - read: src/schema.py
    - modify: src/schema.py
    - write: src/schema.py

agent_b:
  actions:
    - read: src/schema.py
    - wait: 2s
    - modify: src/api.py
    - write: src/api.py
```

Scripts are parsed into typed actions and validated up front, so a
malformed scenario fails before a run starts rather than halfway through
one — a run that dies mid-way still produces evidence (§81), but evidence
of a typo is not what the experiment is for.

Beyond ordinary file operations, a script can request the failure modes §9
and §22 require: crashing, stalling, retrying, deliberately conflicting
writes and deliberately stale reads. Those are first-class actions rather
than test hacks, because the experiment needs to *induce* the conditions it
measures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

__all__ = [
    "Action",
    "ActionKind",
    "AgentScript",
    "Scenario",
    "ScriptError",
    "parse_duration_us",
]


class ScriptError(ValueError):
    """Raised when a script cannot be parsed or is internally inconsistent."""


class ActionKind(StrEnum):
    """What a scripted step does.

    `WRITE` and `MODIFY` are distinct because the events they produce are
    distinct (§16), and attributing a conflict depends on knowing which
    happened.
    """

    READ = "read"
    WRITE = "write"
    CREATE = "create"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"
    LIST = "list"
    TEST = "test"
    CLAIM = "claim"
    RELEASE = "release"
    WAIT = "wait"
    STALL = "stall"
    CRASH = "crash"
    INTENT = "intent"


# Actions that name a file the agent operates on.
_PATH_ACTIONS = frozenset(
    {
        ActionKind.READ,
        ActionKind.WRITE,
        ActionKind.CREATE,
        ActionKind.MODIFY,
        ActionKind.DELETE,
        ActionKind.RENAME,
        ActionKind.CLAIM,
        ActionKind.RELEASE,
    }
)

_DURATION_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)(us|ms|s|m)$")

_DURATION_SCALES = {"us": 1, "ms": 1_000, "s": 1_000_000, "m": 60_000_000}


def parse_duration_us(value: str | int | float) -> int:
    """Parse a duration such as `2s`, `500ms` or a bare number of microseconds.

    Returns integer microseconds, matching the event schema. A bare number
    is microseconds rather than seconds so that scripts and events never
    disagree about units — a silent factor of a million would be very hard
    to notice in a result.
    """
    if isinstance(value, bool):
        raise ScriptError(f"duration must be a string or number, got {value!r}")
    if isinstance(value, (int, float)):
        if value < 0:
            raise ScriptError(f"duration must not be negative, got {value}")
        return int(value)

    match = _DURATION_PATTERN.match(str(value).strip())
    if not match:
        raise ScriptError(
            f"could not parse duration {value!r}; expected a number with a unit "
            f"(us, ms, s, m) such as '2s', or a bare integer of microseconds"
        )
    amount, unit = match.groups()
    return int(float(amount) * _DURATION_SCALES[unit])


@dataclass(frozen=True, slots=True)
class Action:
    """One scripted step."""

    kind: ActionKind
    path: str | None = None
    destination: str | None = None
    content: str | None = None
    old: str | None = None
    new: str | None = None
    duration_us: int = 0
    retries: int = 0
    note: str | None = None
    # Guard: perform this action only if the agent has observed a peer event
    # touching this path. This is how a mock agent "responds to coordination
    # events" (§9) while staying deterministic — same observations, same
    # behaviour. Without it a scripted agent acts identically in every arm
    # and information could never change an outcome, making the C0 to C2
    # contrast unmeasurable with mock agents.
    if_informed_about: str | None = None
    # The mirror: perform this action only if the agent has NOT been told.
    # Together the two let one script express both the informed and the
    # uninformed path, so the arms diverge on behaviour rather than on
    # having been given different scripts.
    if_uninformed_about: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "destination": self.destination,
            "duration_us": self.duration_us,
            "if_informed_about": self.if_informed_about,
            "if_uninformed_about": self.if_uninformed_about,
            "kind": str(self.kind),
            "new": self.new,
            "note": self.note,
            "old": self.old,
            "path": self.path,
            "retries": self.retries,
        }


def _parse_action(raw: Any, *, index: int, agent_id: str) -> Action:
    """Parse one entry of an `actions:` list.

    The compact form `{read: src/schema.py}` and the expanded form
    `{kind: read, path: src/schema.py, ...}` are both accepted; the compact
    form is what §9's example uses.
    """
    where = f"{agent_id}.actions[{index}]"

    if isinstance(raw, str):
        # A bare verb with no argument, e.g. `- test`.
        raw = {raw: None}

    if not isinstance(raw, dict):
        raise ScriptError(f"{where}: expected a mapping or a string, got {type(raw).__name__}")

    verbs = {str(kind) for kind in ActionKind}

    if "kind" in raw:
        kind_name = raw["kind"]
        options = dict(raw)
        options.pop("kind")
    else:
        # Compact form: the single key is the verb.
        keys = [key for key in raw if key in verbs]
        if not keys:
            raise ScriptError(
                f"{where}: unknown action; expected one of {sorted(verbs)}, "
                f"got {sorted(raw)}"
            )
        if len(keys) > 1:
            raise ScriptError(
                f"{where}: expected exactly one action verb "
                f"(one of {sorted(verbs)}), got {sorted(keys)}"
            )
        kind_name = keys[0]
        options = {k: v for k, v in raw.items() if k != kind_name}
        primary = raw[kind_name]

        if isinstance(primary, dict):
            # `{modify: {path: ..., old: ..., new: ...}}` — the verb's value
            # carries the options. §9's own example uses this shape, and
            # dropping it silently would lose `old`/`new` and fail validation
            # with a misleading message.
            for key, value in primary.items():
                options.setdefault(key, value)
        elif primary is not None:
            # A scalar value: the path for path actions, the duration for
            # waits, and a note otherwise.
            if kind_name in {str(k) for k in _PATH_ACTIONS}:
                options.setdefault("path", primary)
            elif kind_name in {"wait", "stall"}:
                options.setdefault("duration", primary)
            else:
                options.setdefault("note", primary)

    try:
        kind = ActionKind(str(kind_name))
    except ValueError as exc:
        raise ScriptError(
            f"{where}: unknown action {kind_name!r}; "
            f"expected one of {sorted(str(k) for k in ActionKind)}"
        ) from exc

    # `duration_us` is what `Action.to_dict` emits, so accepting both is what
    # makes a scenario round-trip through a manifest (§32). Accepting only
    # the authoring spelling would mean a serialised scenario could not be
    # reloaded, which would break reproduction from an export (§82).
    duration = options.pop("duration", options.pop("duration_us", 0))
    action = Action(
        kind=kind,
        path=options.pop("path", None),
        destination=options.pop("to", options.pop("destination", None)),
        content=options.pop("content", None),
        old=options.pop("old", None),
        new=options.pop("new", None),
        duration_us=parse_duration_us(duration) if duration else 0,
        retries=int(options.pop("retries", 0)),
        note=options.pop("note", None),
        if_informed_about=options.pop("if_informed_about", None),
        if_uninformed_about=options.pop("if_uninformed_about", None),
    )

    if options:
        # Unknown keys are refused rather than ignored: a typo in a scenario
        # would otherwise silently change what the experiment ran.
        raise ScriptError(f"{where}: unrecognised option(s) {sorted(options)}")

    if kind in _PATH_ACTIONS and not action.path:
        raise ScriptError(f"{where}: action {kind} requires a path")
    if kind is ActionKind.RENAME and not action.destination:
        raise ScriptError(f"{where}: rename requires a destination ('to:')")
    if kind is ActionKind.MODIFY and (action.old is None or action.new is None):
        raise ScriptError(f"{where}: modify requires both 'old' and 'new'")
    if action.if_informed_about and action.if_uninformed_about:
        raise ScriptError(
            f"{where}: an action cannot require both being informed and "
            "being uninformed about a path"
        )

    return action


@dataclass
class AgentScript:
    """One agent's scripted behaviour."""

    agent_id: str
    actions: list[Action] = field(default_factory=list)
    owned_paths: frozenset[str] = frozenset()
    dependency_paths: frozenset[str] = frozenset()

    @classmethod
    def from_dict(cls, agent_id: str, data: dict[str, Any]) -> AgentScript:
        if not isinstance(data, dict):
            raise ScriptError(f"{agent_id}: expected a mapping, got {type(data).__name__}")

        raw_actions = data.get("actions", [])
        if not isinstance(raw_actions, list):
            raise ScriptError(f"{agent_id}.actions: expected a list")

        return cls(
            agent_id=agent_id,
            actions=[
                _parse_action(raw, index=index, agent_id=agent_id)
                for index, raw in enumerate(raw_actions)
            ],
            owned_paths=frozenset(data.get("owns", ())),
            dependency_paths=frozenset(data.get("depends_on", ())),
        )

    def paths_touched(self) -> frozenset[str]:
        return frozenset(
            path
            for action in self.actions
            for path in (action.path, action.destination)
            if path
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [action.to_dict() for action in self.actions],
            "agent_id": self.agent_id,
            "depends_on": sorted(self.dependency_paths),
            "owns": sorted(self.owned_paths),
        }


@dataclass
class Scenario:
    """A complete multi-agent scenario."""

    agents: dict[str, AgentScript] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Scenario:
        if not isinstance(data, dict) or not data:
            raise ScriptError("a scenario must be a non-empty mapping of agent id to script")
        return cls(
            agents={
                agent_id: AgentScript.from_dict(agent_id, script)
                for agent_id, script in data.items()
            }
        )

    @classmethod
    def from_yaml(cls, source: str | Path) -> Scenario:
        """Load a scenario from YAML text or a file path."""
        import yaml

        text = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
        loaded = yaml.safe_load(text)
        if loaded is None:
            raise ScriptError("scenario is empty")
        return cls.from_dict(loaded)

    def agent_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.agents))

    def contested_paths(self) -> frozenset[str]:
        """Paths more than one agent writes to.

        This is what makes a scenario coordination-sensitive (§37). A
        scenario with no contested path cannot distinguish the arms, and the
        task quality gate uses this to refuse one that only claims to.
        """
        writers: dict[str, set[str]] = {}
        mutating = {
            ActionKind.WRITE,
            ActionKind.CREATE,
            ActionKind.MODIFY,
            ActionKind.DELETE,
            ActionKind.RENAME,
        }
        for script in self.agents.values():
            for action in script.actions:
                if action.kind in mutating and action.path:
                    writers.setdefault(action.path, set()).add(script.agent_id)
        return frozenset(path for path, agents in writers.items() if len(agents) > 1)

    def to_dict(self) -> dict[str, Any]:
        return {agent_id: script.to_dict() for agent_id, script in self.agents.items()}
