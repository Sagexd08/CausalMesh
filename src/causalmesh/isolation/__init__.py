"""Agent isolation: workspaces, path containment and process separation.

Spec §11. This package implements layers L1 (process) and L2 (path) of the
three-layer isolation model in `docs/security.md`. L3 (context injection
accounting) lives in the channel layer, because that is where coordination
bytes actually enter an agent.
"""

from __future__ import annotations

from .workspace import (
    PathEscapeError,
    Workspace,
    WorkspaceError,
    build_run_workspaces,
)

__all__ = [
    "PathEscapeError",
    "Workspace",
    "WorkspaceError",
    "build_run_workspaces",
]
