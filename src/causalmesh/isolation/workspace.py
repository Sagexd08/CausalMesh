"""Agent workspaces and path containment (spec §11).

Every agent gets its own directory tree and may not reach outside it through
the tool API. This module is layer **L2** of the three-layer isolation model
documented in `docs/security.md`; it is deliberately precise about what it
does and does not guarantee.

    L1  process   spawn subprocess, own cwd, scrubbed environment
    L2  path      THIS MODULE — every tool path resolves inside the workspace
    L3  context   single typed injection point, coordination-byte counter

**What L2 guarantees:** an agent cannot read or write a peer's workspace
*through the sanctioned tool API*. Every path is resolved with `realpath` —
which collapses `..`, follows symlinks and resolves Windows junctions — and
then checked for containment before any filesystem operation runs.

**What L2 does not guarantee:** Windows has no `chroot` and no mount
namespaces, so this is not a filesystem jail. A process that bypasses the
tool API can still reach any path its user token permits. Saying otherwise
would be the kind of overclaim §87 forbids. Docker is the optional stronger
boundary for Linux and CI.

Containment is checked *after* resolution, never on the string. A check on
the unresolved text would accept `workspace/../../peer/secrets.py`, and a
symlink planted inside the workspace would defeat it entirely.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "PathEscapeError",
    "Workspace",
    "WorkspaceError",
    "build_run_workspaces",
]


class WorkspaceError(RuntimeError):
    """Raised when a workspace cannot be created or used as specified."""


class PathEscapeError(WorkspaceError):
    """Raised when a path resolves outside its agent's workspace.

    Carries the attempted and resolved paths so the denial can be recorded as
    evidence (§52) rather than as an opaque refusal.
    """

    def __init__(self, requested: str, resolved: Path, root: Path) -> None:
        super().__init__(
            f"path {requested!r} resolves to {resolved}, which is outside the workspace "
            f"root {root}; refusing the operation"
        )
        self.requested = requested
        self.resolved = resolved
        self.root = root


@dataclass(frozen=True)
class Workspace:
    """One agent's isolated working directory.

    `root` is always fully resolved at construction, so every later
    containment check compares two real paths rather than a real path against
    a symlinked or relative spelling of the root.
    """

    agent_id: str
    root: Path
    run_id: str

    @classmethod
    def create(cls, *, base: Path, run_id: str, agent_id: str) -> Workspace:
        root = (Path(base) / run_id / agent_id).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return cls(agent_id=agent_id, root=root, run_id=run_id)

    def resolve(self, relative_path: str) -> Path:
        """Resolve a path and prove it lies inside this workspace.

        Raises `PathEscapeError` on any attempt to leave, whether by `..`
        traversal, an absolute path, a symlink or a Windows junction.
        """
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise WorkspaceError(f"path must be a non-empty string, got {relative_path!r}")

        candidate = Path(relative_path)
        if candidate.is_absolute() or (os.name == "nt" and candidate.drive):
            raise PathEscapeError(relative_path, candidate, self.root)

        resolved = (self.root / candidate).resolve(strict=False)

        if not self._is_contained(resolved):
            raise PathEscapeError(relative_path, resolved, self.root)
        return resolved

    def _is_contained(self, resolved: Path) -> bool:
        """Whether a resolved path lies inside this workspace root.

        `Path.is_relative_to` compares path components, so it cannot be
        fooled by a sibling directory whose name merely shares a prefix
        (`agent_a_backup` next to `agent_a`), which a string `startswith`
        check would wrongly accept.
        """
        try:
            return resolved == self.root or resolved.is_relative_to(self.root)
        except (ValueError, OSError):
            return False

    def contains(self, relative_path: str) -> bool:
        """Non-raising containment check, for gates that report rather than fail."""
        try:
            self.resolve(relative_path)
        except WorkspaceError:
            return False
        return True

    def relative(self, resolved: Path) -> str:
        """Render a resolved path back as a workspace-relative POSIX string.

        Events record workspace-relative paths so that two agents editing
        "the same file" are comparable, and so a chain does not leak absolute
        machine paths into the research record.
        """
        return resolved.relative_to(self.root).as_posix()

    def seed_from(self, fixture: Path) -> None:
        """Copy a task fixture into this workspace.

        Each agent gets its own copy of the repository fixture, so there is
        no shared filesystem between agents (§11) and any interference must
        travel through the coordination channel where it can be measured.
        """
        fixture = Path(fixture)
        if not fixture.is_dir():
            raise WorkspaceError(f"fixture {fixture} is not a directory")
        shutil.copytree(fixture, self.root, dirs_exist_ok=True)

    def list_files(self) -> list[str]:
        """Every file in the workspace, as sorted relative POSIX paths."""
        return sorted(self.relative(path) for path in self.root.rglob("*") if path.is_file())


def build_run_workspaces(
    *, base: Path, run_id: str, agent_ids: list[str], fixture: Path | None = None
) -> dict[str, Workspace]:
    """Create one isolated workspace per agent for a run.

    The resulting layout matches §11:

        base/run_id/agent_a/
        base/run_id/agent_b/

    Workspaces are siblings, never nested, so no agent's root contains
    another's — nesting would make one agent's containment check
    automatically admit the other's files.
    """
    if len(set(agent_ids)) != len(agent_ids):
        raise WorkspaceError(f"agent ids must be unique, got {agent_ids}")

    workspaces = {}
    for agent_id in agent_ids:
        workspace = Workspace.create(base=base, run_id=run_id, agent_id=agent_id)
        if fixture is not None:
            workspace.seed_from(fixture)
        workspaces[agent_id] = workspace
    return workspaces
