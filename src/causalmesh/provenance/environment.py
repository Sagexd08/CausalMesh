"""Capturing what produced a run (spec §30, §32).

Three facts make a result attributable: which code ran, on what, and who
asked for it. The `RunConfig` fields for all three already existed and all
three defaulted to `"unknown"`, because nothing populated them — so every
run executed so far carries no attribution at all.

**Nothing captured here enters the signed chain.** The chain is
bit-reproducible by construction, and a hostname or a wall-clock timestamp
inside it would break that. Provenance sits alongside the evidence,
describing the conditions it was produced under; the evidence stands on its
own hashes.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNKNOWN = "unknown"


def _git(root: Path, *args: str) -> str | None:
    """Run a git command, returning None rather than raising.

    A checkout without git, or a directory that is not a repository, is a
    normal condition — the answer is then "unattributable", which is a fact
    worth recording, not an error worth crashing on.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


@dataclass(frozen=True)
class GitState:
    """The commit a run was produced from, and whether it was clean.

    `dirty` is the load-bearing field. A commit hash alone implies the
    working tree matched that commit, and a result produced from
    uncommitted changes is not reproducible from the hash it names.
    """

    commit: str = UNKNOWN
    branch: str = UNKNOWN
    dirty: bool | None = None

    @classmethod
    def capture(cls, root: Path) -> GitState:
        commit = _git(root, "rev-parse", "HEAD")
        if commit is None:
            return cls()
        status = _git(root, "status", "--porcelain")
        return cls(
            branch=_git(root, "rev-parse", "--abbrev-ref", "HEAD") or UNKNOWN,
            commit=commit,
            # An empty status is a clean tree; None means git answered but
            # the call failed, which is not the same as clean.
            dirty=None if status is None else bool(status),
        )

    @property
    def attributable(self) -> bool:
        """Whether a result can be traced to an exact state of the source."""
        return self.commit != UNKNOWN and self.dirty is False

    def to_dict(self) -> dict[str, Any]:
        return {"branch": self.branch, "commit": self.commit, "dirty": self.dirty}


@dataclass(frozen=True)
class Environment:
    """The machine and interpreter a collection ran on (§32)."""

    python_version: str
    platform_name: str
    machine_id: str
    operator_id: str
    git: GitState = field(default_factory=GitState)

    @classmethod
    def capture(cls, root: Path) -> Environment:
        return cls(
            git=GitState.capture(root),
            machine_id=platform.node() or UNKNOWN,
            operator_id=_operator(),
            platform_name=f"{platform.system()} {platform.release()} ({platform.machine()})",
            python_version=".".join(str(part) for part in sys.version_info[:3]),
        )

    def to_run_config(self) -> dict[str, str]:
        """The subset `RunConfig` carries into each run artifact."""
        return {
            "git_commit": self.git.commit,
            "machine_id": self.machine_id,
            "operator_id": self.operator_id,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "git": self.git.to_dict(),
            "machine_id": self.machine_id,
            "operator_id": self.operator_id,
            "platform": self.platform_name,
            "python_version": self.python_version,
        }


def _operator() -> str:
    """Who ran it, best effort.

    `getpass.getuser` reads the environment, which a CI job may not set. An
    unattributed run is recorded as such rather than guessed at.
    """
    try:
        return getpass.getuser() or UNKNOWN
    except Exception:  # noqa: BLE001 — every failure mode here means "unknown"
        return UNKNOWN


def freeze_hash(config: dict[str, Any]) -> str:
    """A stable digest of the configuration a collection ran under (§33).

    Canonicalised the same way the event protocol canonicalises payloads —
    sorted keys, no incidental whitespace — so the same configuration
    produces the same hash on any machine and in any Python version. A
    freeze hash that depended on dict ordering would report a configuration
    change that never happened.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
