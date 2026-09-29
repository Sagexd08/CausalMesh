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
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "PathEscapeError",
    "Workspace",
    "WorkspaceError",
    "build_run_workspaces",
    "check_path_budget",
]

# MAX_PATH is 260 including the terminating NUL, so 259 usable characters.
_WINDOWS_PATH_LIMIT = 259


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


def _long_paths_enabled() -> bool:
    """Whether Windows will open paths longer than MAX_PATH. True off Windows."""
    if sys.platform != "win32":
        return True
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except OSError:
        return False


def check_path_budget(
    *,
    base: Path,
    run_id: str,
    agent_ids: list[str],
    fixture: Path | None,
    enforce: bool | None = None,
) -> None:
    """Refuse, up front and in plain words, a run whose paths Windows cannot open.

    Without this a checkout that is too deep fails halfway through copying the
    fixture, with `FileNotFoundError`, `WinError 3` or a `shutil.Error` listing
    dozens of paths, and nothing says the cause is the length. The check adds up
    the deepest path a run is certain to create (the workspace root plus the
    deepest file in the fixture) and compares it with MAX_PATH. It refuses only
    what is certain to fail: a margin for files created later (`__pycache__`, an
    agent's own) was tried and refused checkouts, 60 and 99 characters deep, whose
    runs all completed. Something written below the fixture can still overflow a
    checkout that is within a few dozen characters of the limit; that fails as it
    always did, and `docs/backlog.md` says so.

    It is skipped where the limit does not apply: off Windows, or where the
    machine has long paths enabled. `enforce` overrides that, for tests.

    Raises:
        WorkspaceError: naming the length, the limit, and both ways out.
    """
    if enforce is None:
        enforce = not _long_paths_enabled()
    if not enforce:
        return
    deepest_file = 0
    if fixture is not None and Path(fixture).is_dir():
        fixture = Path(fixture)
        deepest_file = max(
            (len(p.relative_to(fixture).as_posix()) + 1 for p in fixture.rglob("*")), default=0
        )
    roots = [base / run_id / agent for agent in agent_ids] + [base / f"{run_id}_integrated"]
    deepest_root = max(roots, key=lambda root: len(os.path.abspath(root)))
    needed = len(os.path.abspath(deepest_root)) + deepest_file
    if needed > _WINDOWS_PATH_LIMIT:
        raise WorkspaceError(
            f"run {run_id!r} needs paths up to about {needed} characters, and Windows opens "
            f"at most {_WINDOWS_PATH_LIMIT} unless long paths are enabled. The workspace would "
            f"be {os.path.abspath(deepest_root)}. Move the checkout somewhere shorter, use a "
            "shorter experiment id (it is part of every run id), or enable long paths "
            r"(HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1)."
        )


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
    check_path_budget(base=base, run_id=run_id, agent_ids=agent_ids, fixture=fixture)

    workspaces = {}
    for agent_id in agent_ids:
        workspace = Workspace.create(base=base, run_id=run_id, agent_id=agent_id)
        if fixture is not None:
            workspace.seed_from(fixture)
        workspaces[agent_id] = workspace
    return workspaces
