"""Finding the coding agents and infrastructure on this machine.

Everything here is **probed, never assumed**. A tool on `PATH` is not a
working tool: on the machine this was written for, five agent CLIs were
installed and one of them refused to start because the Node runtime was too
old. A connector list built from `shutil.which` alone would have reported it
as available and failed at run time.

So a probe has three outcomes, not two:

- **available** — it ran and reported a version
- **degraded** — it exists and is executable, but did not answer correctly
- **absent** — not on PATH

`degraded` is the one that matters. Collapsing it into `absent` hides an
installation the operator probably wants to fix; collapsing it into
`available` produces a run that dies partway through.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any

# A probe must not hang the CLI. Agent binaries are large and cold-start
# slowly, so this is generous — but bounded.
PROBE_TIMEOUT_S = 25


class Availability(str, Enum):
    AVAILABLE = "available"
    DEGRADED = "degraded"
    ABSENT = "absent"


@dataclass(frozen=True)
class Probe:
    """What one tool on this machine turned out to be."""

    name: str
    kind: str  # "agent" or "infra"
    availability: Availability
    path: str | None = None
    version: str | None = None
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.availability is Availability.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "availability": self.availability.value,
            "detail": self.detail,
            "kind": self.kind,
            "name": self.name,
            "path": self.path,
            "usable": self.usable,
            "version": self.version,
        }


@dataclass(frozen=True)
class ToolSpec:
    """How to look for one tool, and how to read its answer."""

    name: str
    kind: str
    command: str
    version_args: tuple[str, ...] = ("--version",)
    # Some CLIs print their version to stderr, or wrap it in a banner.
    version_pattern: str = r"\d+\.\d+(?:\.\d+)?"
    description: str = ""


# The agents this build knows how to look for. Presence here is not a claim
# that a connector can drive it — `connectors/` says which are drivable.
AGENT_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("claude", "agent", "claude", description="Claude Code"),
    ToolSpec("codex", "agent", "codex", description="OpenAI Codex CLI"),
    ToolSpec("gemini", "agent", "gemini", description="Gemini CLI"),
    ToolSpec("copilot", "agent", "copilot", description="GitHub Copilot CLI"),
    ToolSpec("cursor-agent", "agent", "cursor-agent", description="Cursor agent"),
    ToolSpec("aider", "agent", "aider", description="Aider"),
    ToolSpec("opencode", "agent", "opencode", description="OpenCode"),
)

INFRA_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("git", "infra", "git", description="Required: fixtures are git checkouts"),
    ToolSpec("docker", "infra", "docker", description="Optional: the C0 jail on Linux"),
    ToolSpec("ollama", "infra", "ollama", description="Optional: local model server"),
    ToolSpec("python", "infra", "python", description="Required: task integration tests"),
)


def _run(command: str, args: tuple[str, ...]) -> tuple[int | None, str]:
    """Invoke a tool by its RESOLVED path, combining both streams.

    The resolved path is not a convenience. On Windows every npm-installed
    agent is a `.cmd` shim, and passing the bare name to `subprocess.run`
    fails with "cannot find the file specified" even though `shutil.which`
    just located it — the extensionless name is not directly executable.
    Probing by name reported three of four working agents as broken.

    Both streams are read because version output is not consistently on
    stdout — the Copilot CLI writes its Node-version refusal to stderr, and
    treating that as no output would misreport it as silent rather than
    broken.
    """
    try:
        completed = subprocess.run(
            [command, *args],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
            # A probe must never inherit a terminal: an agent CLI that
            # decides it is interactive will wait for input forever.
            stdin=subprocess.DEVNULL,
            env={**os.environ, "NO_COLOR": "1"},
        )
    except subprocess.TimeoutExpired:
        return None, "timed out"
    except OSError as exc:
        return None, str(exc)
    return completed.returncode, f"{completed.stdout}\n{completed.stderr}".strip()


def probe(spec: ToolSpec) -> Probe:
    """Find one tool and establish whether it actually works."""
    resolved = shutil.which(spec.command)
    if resolved is None:
        return Probe(
            availability=Availability.ABSENT,
            detail="not on PATH",
            kind=spec.kind,
            name=spec.name,
        )

    code, output = _run(resolved, spec.version_args)
    if code is None:
        return Probe(
            availability=Availability.DEGRADED,
            detail=output,
            kind=spec.kind,
            name=spec.name,
            path=resolved,
        )

    match = re.search(spec.version_pattern, output)
    if code != 0 or match is None:
        # Installed and executable, but it did not answer. The first line
        # of its output is usually the reason, and is worth surfacing
        # verbatim rather than paraphrasing.
        first = next((line for line in output.splitlines() if line.strip()), "")
        return Probe(
            availability=Availability.DEGRADED,
            detail=first[:200] or f"exited {code} with no output",
            kind=spec.kind,
            name=spec.name,
            path=resolved,
        )

    return Probe(
        availability=Availability.AVAILABLE,
        detail=spec.description,
        kind=spec.kind,
        name=spec.name,
        path=resolved,
        version=match.group(0),
    )


def discover(specs: tuple[ToolSpec, ...] | None = None) -> list[Probe]:
    """Probe every known tool.

    Sequential rather than parallel: a cold agent binary can take seconds,
    but a dozen of them starting at once on a laptop is worse than the wait,
    and this runs interactively where predictable beats fast.
    """
    return [probe(spec) for spec in (specs or (*AGENT_SPECS, *INFRA_SPECS))]


def available_agents(probes: list[Probe] | None = None) -> list[Probe]:
    """Only the agents that answered correctly."""
    return [p for p in (probes or discover(AGENT_SPECS)) if p.kind == "agent" and p.usable]
