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

**Who and where are not recorded in the clear by default.** `data/manifests/`
is tracked, so a manifest written with the real hostname and OS username
publishes the identity of whoever committed it; one did (see
`docs/backlog.md`). By default `machine_id` and `operator_id` are therefore a
labelled, keyed digest -- `keyed:` plus 16 hex digits of an HMAC-SHA-256 --
or `unknown` when no key can be kept. The choice and its reasons:

* `unknown` alone is the cheapest answer, but it makes two manifests from
  two machines indistinguishable, and "were these produced on the same
  machine" is a real reproducibility question.
* A bare hash of a hostname or username is not anonymous: both come from a
  tiny space and can be enumerated. The digest is therefore keyed with a
  random 256-bit secret generated on first use and stored in the git
  directory (`<git-common-dir>/causalmesh/identity.key`, mode 0600), which
  is never tracked and never pushed. Without the key the digest cannot be
  tested against a guess. The key is shared by every worktree of one
  clone, so those agree with each other.
* The cost of that is one small file in `.git` and no new dependency
  (`hmac` and `secrets` are standard library). Where there is no git
  directory, or it is unwritable, the answer falls back to `unknown`
  rather than to an unkeyed hash.
* Honest limit: a digest compares only within one clone. The same machine
  cloned twice gets two different digests, so "different digest" means
  "different machine or different clone", never "different person". Host
  and user are derived under separate labels, so one cannot be matched to
  the other.

Pass `record_host=True` (CLI: `--record-host`) to record the real values,
for a private run that will not be committed.
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import json
import os
import platform
import secrets
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
    def capture(cls, root: Path, *, record_host: bool = False) -> Environment:
        """Capture the environment.

        With `record_host` false (the default) `machine_id` and
        `operator_id` are keyed digests or `unknown`, never the real
        hostname or username. With it true they are the real values.
        """
        host = platform.node()
        operator = _operator()
        if record_host:
            machine_id = host or UNKNOWN
        else:
            machine_id = _keyed_digest(root, "machine", host)
            operator = _keyed_digest(root, "operator", operator)
        return cls(
            git=GitState.capture(root),
            machine_id=machine_id,
            operator_id=operator,
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


DIGEST_PREFIX = "keyed:"
_DIGEST_HEX = 16
_KEY_BYTES = 32


def _identity_key(root: Path) -> bytes | None:
    """The per-clone secret, created on first use; None if it cannot be kept.

    Lives under the git common directory so it is untracked by construction
    and shared by worktrees. Created with O_EXCL and mode 0600 so two racing
    captures cannot produce two keys.
    """
    common = _git(root, "rev-parse", "--git-common-dir")
    if common is None:
        return None
    directory = Path(root) / common / "causalmesh"
    path = directory / "identity.key"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(secrets.token_hex(_KEY_BYTES) + "\n")
        key = path.read_text(encoding="ascii").strip()
        if len(key) != _KEY_BYTES * 2:
            return None
        return bytes.fromhex(key)
    except (OSError, ValueError):
        return None


def _keyed_digest(root: Path, label: str, value: str | None) -> str:
    """A labelled, keyed, truncated digest of `value`, or `unknown`.

    Never falls back to an unkeyed hash: a missing key or a missing value is
    `unknown`, which is true, rather than a digest that could be guessed.
    """
    if not value or value == UNKNOWN:
        return UNKNOWN
    key = _identity_key(root)
    if key is None:
        return UNKNOWN
    mac = hmac.new(key, f"{label}\0{value}".encode(), hashlib.sha256)
    return DIGEST_PREFIX + mac.hexdigest()[:_DIGEST_HEX]


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
