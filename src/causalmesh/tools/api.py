"""The controlled tool API (spec §12).

Exactly twelve operations, and no unrestricted host shell:

    read_file    write_file   create_file  modify_file
    delete_file  rename_file  list_files   run_command
    run_tests    git_status   git_diff

Every one resolves its paths through the agent's `Workspace`, so L2
containment applies uniformly rather than being remembered at each call site.
Every one is reached through `LifecycleBoundary.invoke`, so no tool can run
without passing the gate and being recorded.

`run_command` is the dangerous one and is treated accordingly: it takes an
argument list rather than a shell string, runs with the workspace as its
working directory and a scrubbed environment, and refuses anything not on an
explicit allowlist. A general shell would let an agent reach any path its
user token permits, which would silently void every isolation claim in
`docs/security.md`.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..isolation import Workspace

__all__ = [
    "TOOL_NAMES",
    "ToolError",
    "Toolbox",
]


TOOL_NAMES = (
    "read_file",
    "write_file",
    "create_file",
    "modify_file",
    "delete_file",
    "rename_file",
    "list_files",
    "run_command",
    "run_tests",
    "git_status",
    "git_diff",
)

# Commands an agent may run. An allowlist rather than a denylist: a denylist
# is a promise to have imagined every dangerous command, which is not a
# promise this project can keep.
ALLOWED_COMMANDS = frozenset({"python", "pytest", "git"})

# Environment variables a subprocess inherits. An allowlist, so an operator's
# API keys and proxy settings cannot reach an agent and runs do not depend on
# whose shell launched them (§3).
#
# APPDATA and LOCALAPPDATA are here for a concrete reason found by running the
# suite: on Windows, user-site packages live under %APPDATA%\Python, and
# dropping it makes `python -m pytest` fail with "No module named pytest".
# Every task's integration test would then fail identically in every arm, and
# the experiment would report uniform failure while looking like it ran.
_INHERITED_ENVIRONMENT = (
    "PATH",
    "SYSTEMROOT",
    "COMSPEC",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
    "APPDATA",
    "LOCALAPPDATA",
    # Needed by some Windows Python builds to locate the interpreter's own
    # installation when PATH alone is insufficient.
    "PATHEXT",
)


# Bounded so a hung or runaway command cannot stall a run indefinitely (§22).
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120


class ToolError(RuntimeError):
    """Raised when a tool cannot perform the operation as requested."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """The outcome of a subprocess, recorded rather than interpreted."""

    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def to_event_payload(self) -> dict[str, Any]:
        """The deterministic subset that may enter the signed event chain.

        Command output is excluded, and so is any digest of it. `pytest -q`
        prints "1 passed in 0.73s" and the elapsed time differs every run,
        so the text is not reproducible — and **a digest of
        non-reproducible bytes is just as non-reproducible**. An earlier
        version of this method included `output_sha256` and reintroduced
        exactly the failure it was meant to fix, hidden behind a hash
        rather than visible as text.

        What remains is everything the analysis actually needs: which
        command ran, whether it succeeded, and whether it timed out. Task
        success is decided from the exit code (§38), never from parsing
        output, so nothing downstream depends on the text.

        The full output is still kept, as a run artifact via `to_dict`. It
        is evidence a human can read, not an input to the integrity record.
        """
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
        }

    def to_dict(self) -> dict[str, Any]:
        """The full result, including output, for run artifacts and debugging.

        This goes to `data/raw/<run>/commands/`, never into the event
        payload — see `to_event_payload`.
        """
        return {
            "command": list(self.command),
            "exit_code": self.exit_code,
            # Truncated: full output can be megabytes, and a run artifact is
            # evidence, not a build log.
            "stderr": self.stderr[-4000:],
            "stdout": self.stdout[-4000:],
            "timed_out": self.timed_out,
        }


class Toolbox:
    """The tool surface available to one agent inside one workspace.

    Constructed per agent, so a tool call can never name another agent's
    workspace: there is no parameter through which to express it.
    """

    def __init__(self, workspace: Workspace, *, command_timeout: int | None = None) -> None:
        self.workspace = workspace
        self._timeout = command_timeout or DEFAULT_COMMAND_TIMEOUT_SECONDS

    # -- reads ------------------------------------------------------------

    def read_file(self, path: str) -> str:
        resolved = self.workspace.resolve(path)
        if not resolved.is_file():
            raise ToolError(f"{path!r} does not exist or is not a file")
        return resolved.read_text(encoding="utf-8")

    def list_files(self, subdirectory: str | None = None) -> list[str]:
        if subdirectory is None:
            return self.workspace.list_files()
        resolved = self.workspace.resolve(subdirectory)
        if not resolved.is_dir():
            raise ToolError(f"{subdirectory!r} is not a directory")
        return sorted(
            self.workspace.relative(child)
            for child in resolved.rglob("*")
            if child.is_file()
        )

    # -- writes -----------------------------------------------------------

    def write_file(self, path: str, content: str) -> int:
        """Write a file, creating parent directories. Returns bytes written."""
        resolved = self.workspace.resolve(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        resolved.write_bytes(data)
        return len(data)

    def create_file(self, path: str, content: str = "") -> int:
        """Create a file that must not already exist.

        Distinct from `write_file` so that "I am adding this" and "I am
        replacing this" are different events (§16) — the difference matters
        when attributing a conflicting edit.
        """
        resolved = self.workspace.resolve(path)
        if resolved.exists():
            raise ToolError(f"{path!r} already exists; use write_file to replace it")
        resolved.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        resolved.write_bytes(data)
        return len(data)

    def modify_file(self, path: str, old: str, new: str) -> int:
        """Replace an exact substring. Returns the number of replacements.

        A targeted edit rather than a whole-file overwrite, because a
        conflicting write is only interesting if we know it was a *change* to
        something rather than a wholesale replacement.
        """
        resolved = self.workspace.resolve(path)
        if not resolved.is_file():
            raise ToolError(f"{path!r} does not exist or is not a file")
        original = resolved.read_text(encoding="utf-8")
        if old not in original:
            raise ToolError(f"{old!r} not found in {path!r}")
        count = original.count(old)
        resolved.write_text(original.replace(old, new), encoding="utf-8")
        return count

    def delete_file(self, path: str) -> None:
        resolved = self.workspace.resolve(path)
        if not resolved.is_file():
            raise ToolError(f"{path!r} does not exist or is not a file")
        resolved.unlink()

    def rename_file(self, source: str, destination: str) -> None:
        # Both ends are resolved, so a rename cannot be used to write outside
        # the workspace via its destination.
        resolved_source = self.workspace.resolve(source)
        resolved_destination = self.workspace.resolve(destination)
        if not resolved_source.exists():
            raise ToolError(f"{source!r} does not exist")
        if resolved_destination.exists():
            raise ToolError(f"{destination!r} already exists")
        resolved_destination.parent.mkdir(parents=True, exist_ok=True)
        resolved_source.rename(resolved_destination)

    # -- execution --------------------------------------------------------

    def run_command(self, command: Sequence[str], *, timeout: int | None = None) -> CommandResult:
        """Run an allowlisted command inside the workspace.

        No shell. `shell=True` would let an agent reach any path its user
        token permits through `&&`, redirection or a subshell, voiding every
        isolation claim this project makes.
        """
        if isinstance(command, str):
            raise ToolError(
                "run_command takes a list of arguments, not a shell string; "
                "shell interpretation would bypass workspace containment"
            )
        parts = [str(part) for part in command]
        if not parts:
            raise ToolError("run_command requires a non-empty command")

        executable = os.path.basename(parts[0]).lower().removesuffix(".exe")
        if executable not in ALLOWED_COMMANDS:
            raise ToolError(
                f"command {executable!r} is not allowlisted "
                f"(allowed: {sorted(ALLOWED_COMMANDS)})"
            )

        try:
            completed = subprocess.run(
                parts,
                cwd=self.workspace.root,
                capture_output=True,
                text=True,
                timeout=timeout or self._timeout,
                env=self._scrubbed_environment(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            # A timeout is data, not a crash: §22 treats a hung command as an
            # injectable failure mode the run must survive.
            return CommandResult(
                command=tuple(parts),
                exit_code=-1,
                stdout=(exc.stdout or b"").decode("utf-8", "replace")
                if isinstance(exc.stdout, bytes)
                else (exc.stdout or ""),
                stderr=f"timed out after {timeout or self._timeout}s",
                timed_out=True,
            )
        except OSError as exc:
            raise ToolError(f"could not run {parts[0]!r}: {exc}") from exc

        return CommandResult(
            command=tuple(parts),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def run_tests(self, target: str | None = None) -> CommandResult:
        """Run the workspace's tests.

        Success is decided by the harness from the exit code, never by the
        agent's own report (§38).
        """
        command = ["python", "-m", "pytest", "-q"]
        if target is not None:
            # Resolved so a test target cannot escape the workspace either.
            command.append(self.workspace.relative(self.workspace.resolve(target)))
        return self.run_command(command)

    def git_status(self) -> CommandResult:
        return self.run_command(["git", "status", "--porcelain"])

    def git_diff(self) -> CommandResult:
        return self.run_command(["git", "diff"])

    # -- environment ------------------------------------------------------

    def _scrubbed_environment(self) -> dict[str, str]:
        """A minimal environment for subprocesses (L1 of the isolation model).

        Only what a Python or git process genuinely needs is passed through.
        Inheriting the full environment would carry API keys, proxy settings
        and paths that could point an agent outside its workspace — and would
        make runs depend on the operator's shell, breaking the §3 requirement
        that everything but the manipulated factors be held constant.
        """
        environment = {
            name: os.environ[name] for name in _INHERITED_ENVIRONMENT if name in os.environ
        }
        # Deterministic hashing and no stray .pyc files in the workspace.
        environment["PYTHONHASHSEED"] = "0"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        return environment
