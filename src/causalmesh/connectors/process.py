"""Driving a real coding-agent CLI as a subprocess.

A connector turns an installed agent into something the run loop can use.
It is deliberately thin: it starts a process in a workspace, hands it a
prompt, waits, and reads back what it said. Everything about coordination —
what the agent was told about its peers, what it was allowed to write — is
enforced by the layers that already exist, and a connector that reached
around them would reproduce the channel-bypass defect recorded in
`docs/backlog.md`.

**A run driven this way is not reproducible.** Hosted models are not
deterministic, the agent's own version changes under it, and the same prompt
produces different work on different days. Every artifact a connector
contributes to is stamped `reproducible: false`, and §84 already says
temperature alone is not a reproducibility guarantee. The chain still signs
and verifies: it records what happened, which is a different property from
being able to repeat it.

**A run driven this way costs money.** One trivial probe invocation of
Claude Code during development cost $0.36. Nothing here runs an agent
unless the caller asked for it by name.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT_S = 300


class ConnectorError(RuntimeError):
    """An agent process could not be started, or did not answer usefully."""


@dataclass(frozen=True)
class AgentInvocation:
    """One completed call into a real agent CLI."""

    agent: str
    prompt: str
    reply: str
    exit_code: int
    duration_s: float
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    permission_denials: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and bool(self.reply)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "cost_usd": self.cost_usd,
            "duration_s": round(self.duration_s, 3),
            "exit_code": self.exit_code,
            "input_tokens": self.input_tokens,
            "ok": self.ok,
            "output_tokens": self.output_tokens,
            "permission_denials": self.permission_denials,
            "reply": self.reply,
        }


@dataclass(frozen=True)
class ConnectorSpec:
    """How to invoke one agent headlessly, and how to read its answer.

    `argv` is a template: `{prompt}` is substituted, everything else is
    passed through. Keeping it declarative means adding an agent is a data
    change rather than a new subclass.
    """

    name: str
    command: str
    argv: tuple[str, ...]
    reply_field: str | None = None  # a JSON key, or None for raw stdout
    cost_field: str | None = None
    denials_field: str | None = None

    def build(self, prompt: str) -> list[str]:
        return [arg.replace("{prompt}", prompt) for arg in self.argv]


# Only agents whose headless interface has actually been exercised appear
# here. An entry is a claim that this build can drive it, so an untested
# one would be exactly the kind of "complete because it compiles" the
# standing commitments forbid.
SPECS: dict[str, ConnectorSpec] = {
    "claude": ConnectorSpec(
        argv=("-p", "{prompt}", "--output-format", "json"),
        command="claude",
        cost_field="total_cost_usd",
        denials_field="permission_denials",
        name="claude",
        reply_field="result",
    ),
    "codex": ConnectorSpec(
        argv=("exec", "--skip-git-repo-check", "{prompt}"),
        command="codex",
        name="codex",
        reply_field=None,
    ),
}


def _resolve(command: str) -> str:
    """Find a command, and return the path rather than the name.

    On Windows an npm-installed agent is a `.cmd` shim and the bare name is
    not directly executable — see `discovery._run`.
    """
    resolved = shutil.which(command)
    if resolved is None:
        raise ConnectorError(
            f"{command!r} is not on PATH. Run `causalmesh connectors list` to see "
            "what this machine has."
        )
    return resolved


def _read_json(text: str) -> dict[str, Any] | None:
    """Parse an agent's JSON answer, tolerating surrounding noise.

    Agent CLIs print progress and warnings around their structured output,
    so the whole stream is rarely valid JSON. The last complete object is
    the result: earlier ones are progress frames.
    """
    for line in reversed([line for line in text.splitlines() if line.strip()]):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def invoke(
    spec: ConnectorSpec,
    prompt: str,
    *,
    workspace: Path,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    env: dict[str, str] | None = None,
) -> AgentInvocation:
    """Run one agent turn in `workspace` and read back what it said."""
    workspace = Path(workspace)
    if not workspace.is_dir():
        raise ConnectorError(f"workspace {workspace} does not exist")

    command = _resolve(spec.command)
    loop = asyncio.get_running_loop()
    started = loop.time()

    process = await asyncio.create_subprocess_exec(
        command,
        *spec.build(prompt),
        cwd=str(workspace),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Never inherit a terminal: an agent that decides it is interactive
        # waits for input that will never come, and the run hangs rather
        # than failing.
        stdin=asyncio.subprocess.DEVNULL,
        env={**os.environ, "NO_COLOR": "1", **(env or {})},
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise ConnectorError(
            f"{spec.name} did not finish within {timeout_s}s. A hung agent is a "
            "failed turn, not a reason to wait longer."
        ) from None

    duration = loop.time() - started
    out = stdout.decode("utf-8", errors="replace")
    err = stderr.decode("utf-8", errors="replace")

    parsed = _read_json(out) if spec.reply_field else None
    if spec.reply_field and parsed is not None:
        reply = str(parsed.get(spec.reply_field) or "")
    else:
        reply = out.strip() or err.strip()

    denials = 0
    if spec.denials_field and parsed:
        value = parsed.get(spec.denials_field)
        denials = len(value) if isinstance(value, list) else int(value or 0)

    usage = (parsed or {}).get("usage") or {}
    return AgentInvocation(
        agent=spec.name,
        cost_usd=(parsed or {}).get(spec.cost_field) if spec.cost_field else None,
        duration_s=duration,
        exit_code=process.returncode if process.returncode is not None else -1,
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        permission_denials=denials,
        prompt=prompt,
        raw=parsed or {},
        reply=reply,
    )


def spec_for(name: str) -> ConnectorSpec:
    try:
        return SPECS[name]
    except KeyError:
        raise ConnectorError(
            f"no connector for {name!r}; this build can drive {sorted(SPECS)}"
        ) from None
