"""Turning a model's reply into a tool call (spec §8, §12).

A model emits text. The tool boundary takes a named operation with typed
arguments. This module is the join, and it is deliberately strict.

**Why strict.** A permissive parser that guesses what the model meant would
make the agent's behaviour depend on the parser's guesses, not the model's
output — and two runs of the "same" model would differ because the parser
resolved an ambiguity differently. Every rejection is recorded with its
reason (§52), so a model that cannot follow the protocol shows up as
measurable non-compliance rather than as silently degraded behaviour.

**The wire format** is one JSON object per turn:

    {"tool": "write_file", "arguments": {"path": "...", "content": "..."},
     "reasoning": "why", "done": false}

JSON rather than a bespoke syntax because every model has seen a great deal
of it, and because a malformed object is unambiguously malformed — whereas
a bespoke format degrades into "did it mean this?".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..tools.api import TOOL_NAMES

__all__ = [
    "PARSE_FAILURE_KINDS",
    "ParsedAction",
    "ProtocolError",
    "parse_action",
    "system_prompt",
]


class ProtocolError(ValueError):
    """A model reply could not be turned into a tool call."""

    def __init__(self, message: str, *, kind: str) -> None:
        super().__init__(message)
        self.kind = kind


PARSE_FAILURE_KINDS = (
    "no_json",
    "malformed_json",
    "not_an_object",
    "missing_tool",
    "unknown_tool",
    "bad_arguments",
)

REQUIRED_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "read_file": ("path",),
    "write_file": ("path", "content"),
    "create_file": ("path",),
    "modify_file": ("path", "old", "new"),
    "delete_file": ("path",),
    "rename_file": ("source", "destination"),
    "list_files": (),
    "run_command": ("command",),
    "run_tests": (),
    "git_status": (),
    "git_diff": (),
}

PATH_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "read_file": ("path",),
    "write_file": ("path",),
    "create_file": ("path",),
    "modify_file": ("path",),
    "delete_file": ("path",),
    "rename_file": ("source", "destination"),
    "list_files": (),
    "run_command": (),
    "run_tests": (),
    "git_status": (),
    "git_diff": (),
}


@dataclass(frozen=True)
class ParsedAction:
    """One tool call a model asked for."""

    tool: str
    arguments: dict[str, Any]
    reasoning: str = ""
    done: bool = False
    paths: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "done": self.done,
            "paths": list(self.paths),
            "reasoning": self.reasoning,
            "tool": self.tool,
        }


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Find the JSON object in a reply.

    Models wrap JSON in prose and code fences no matter how the prompt is
    worded. Handling the two common wrappers is not "guessing what it
    meant" — the object itself is still parsed strictly, and anything that
    is not a well-formed object is still rejected.
    """
    fenced = _FENCE.search(text)
    if fenced:
        return fenced.group(1)

    start = text.find("{")
    if start == -1:
        raise ProtocolError("reply contains no JSON object", kind="no_json")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ProtocolError("reply has an unterminated JSON object", kind="malformed_json")


def parse_action(reply: str) -> ParsedAction:
    """Parse a model reply into a tool call, or raise `ProtocolError`."""
    extracted = _extract_json(reply)
    try:
        decoded = json.loads(extracted)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"reply is not valid JSON: {exc}", kind="malformed_json") from exc

    if not isinstance(decoded, dict):
        raise ProtocolError(
            f"reply JSON is a {type(decoded).__name__}, not an object", kind="not_an_object"
        )

    tool = decoded.get("tool")
    done = bool(decoded.get("done", False))

    if tool is None and done:
        return ParsedAction(
            tool="", arguments={}, reasoning=str(decoded.get("reasoning", "")), done=True
        )
    if not isinstance(tool, str) or not tool:
        raise ProtocolError("reply has no 'tool' field", kind="missing_tool")
    if tool not in TOOL_NAMES:
        raise ProtocolError(
            f"unknown tool {tool!r}; the controlled API is {sorted(TOOL_NAMES)}",
            kind="unknown_tool",
        )

    arguments = decoded.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ProtocolError(
            f"'arguments' is a {type(arguments).__name__}, not an object",
            kind="bad_arguments",
        )

    missing = [name for name in REQUIRED_ARGUMENTS[tool] if name not in arguments]
    if missing:
        raise ProtocolError(
            f"{tool} requires {list(REQUIRED_ARGUMENTS[tool])}, missing {missing}",
            kind="bad_arguments",
        )

    paths = tuple(str(arguments[name]) for name in PATH_ARGUMENTS[tool] if name in arguments)
    return ParsedAction(
        tool=tool,
        arguments=arguments,
        reasoning=str(decoded.get("reasoning", "")),
        done=done,
        paths=paths,
    )


def system_prompt(
    *, agent_id: str, role_description: str, owns: list[str], depends_on: list[str]
) -> str:
    """The instruction every model-backed agent receives.

    Identical in structure across arms. What differs between arms is the
    *coordination* content injected each turn by the channel — if the
    system prompt differed too, the C0/C2 contrast would confound
    information with instruction.
    """
    owned = ", ".join(sorted(owns)) or "(nothing specific)"
    depends = ", ".join(sorted(depends_on)) or "(nothing)"
    tools = "\n".join(
        f"  {name}({', '.join(REQUIRED_ARGUMENTS[name]) or 'no arguments'})" for name in TOOL_NAMES
    )
    return f"""You are {agent_id}, a coding agent working in a shared repository.

Your role: {role_description}
Files you own: {owned}
Files you depend on: {depends}

You act by emitting exactly one JSON object per turn, and nothing else:

{{"tool": "<name>", "arguments": {{...}}, "reasoning": "<why>", "done": false}}

Set "done": true when your work is complete. On that turn you may omit
"tool".

Available tools:
{tools}

Rules:
- One JSON object per reply. No prose outside it.
- Paths are relative to your workspace root. You cannot reach outside it.
- Only write files you own. Writes to files owned by another agent may be
  refused, and a refusal is recorded.
- run_command takes a list of arguments, not a shell string.
"""
