"""Manifests: SHA-256 over every artifact a collection produced (§30, §31).

A manifest is what survives the raw data. `data/raw/` is untracked — it is
large, machine-specific and reproducible from configuration plus seed — so
without a manifest a published figure has nothing behind it once the
directory is gone. The manifest is tracked in git precisely so a number can
be traced back to the run that produced it, and so a later copy of that run
can be shown to be the same bytes.

**A manifest proves integrity, not authenticity.** It records that the
artifact hashed to this value when the manifest was written. What makes the
contents trustworthy is the signed chain inside each artifact, which the
verifier checks independently. The two answer different questions and
neither substitutes for the other.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from causalmesh.provenance.environment import Environment, freeze_hash

MANIFEST_VERSION = 1

_BLOCK = 1 << 20


class ManifestError(ValueError):
    """A manifest could not be written, read or checked."""


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(_BLOCK):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ArtifactEntry:
    """One file, as it stood when the manifest was written."""

    path: str
    sha256: str
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {"bytes": self.bytes, "path": self.path, "sha256": self.sha256}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactEntry:
        return cls(bytes=int(data["bytes"]), path=data["path"], sha256=data["sha256"])


@dataclass(frozen=True)
class CheckResult:
    """The outcome of checking a manifest against what is on disk.

    Missing, changed and added are kept apart because they mean different
    things: a missing artifact is lost evidence, a changed one is mutated
    evidence (§31 forbids it outright), and an added one is merely
    unrecorded — a later run in the same directory, most often.
    """

    experiment_id: str
    checked: int
    missing: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    added: tuple[str, ...] = ()

    @property
    def intact(self) -> bool:
        """True only when every recorded artifact is present and unchanged.

        Added files do not break integrity: they were never claimed by the
        manifest, so their presence says nothing about the evidence it
        does cover.
        """
        return not self.missing and not self.changed

    def to_dict(self) -> dict[str, Any]:
        return {
            "added": list(self.added),
            "changed": list(self.changed),
            "checked": self.checked,
            "experiment_id": self.experiment_id,
            "intact": self.intact,
            "missing": list(self.missing),
        }


@dataclass
class Manifest:
    """Everything needed to trace a collection's figures back to its runs."""

    experiment_id: str
    created_at: str
    environment: dict[str, Any]
    config_freeze: str
    artifacts: list[ArtifactEntry] = field(default_factory=list)
    version: int = MANIFEST_VERSION

    @property
    def total_bytes(self) -> int:
        return sum(entry.bytes for entry in self.artifacts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifacts": [entry.to_dict() for entry in self.artifacts],
            "config_freeze": self.config_freeze,
            "created_at": self.created_at,
            "environment": self.environment,
            "experiment_id": self.experiment_id,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Manifest:
        try:
            return cls(
                artifacts=[ArtifactEntry.from_dict(e) for e in data["artifacts"]],
                config_freeze=data["config_freeze"],
                created_at=data["created_at"],
                environment=data["environment"],
                experiment_id=data["experiment_id"],
                version=int(data.get("version", MANIFEST_VERSION)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"malformed manifest: {exc}") from exc

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return path

    @classmethod
    def read(cls, path: Path) -> Manifest:
        try:
            return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"{path}: could not read manifest: {exc}") from exc


def build(
    experiment_dir: Path,
    *,
    repository_root: Path,
    config: dict[str, Any] | None = None,
    now: datetime | None = None,
    record_host: bool = False,
) -> Manifest:
    """Hash every artifact in a collection and record what produced it.

    The manifest is tracked, so by default it carries no hostname or OS
    username, only keyed digests of them (see `Environment`). `record_host`
    records the real values and is for manifests that will not be committed.
    """
    experiment_dir = Path(experiment_dir)
    if not experiment_dir.is_dir():
        raise ManifestError(f"{experiment_dir} is not a directory")

    entries = []
    for path in sorted(experiment_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name == "index.db":
            continue
        entries.append(
            ArtifactEntry(
                bytes=path.stat().st_size,
                path=path.relative_to(experiment_dir).as_posix(),
                sha256=hash_file(path),
            )
        )

    if not entries:
        raise ManifestError(f"{experiment_dir} contains no artifacts to record")

    stamp = (now or datetime.now(UTC)).isoformat()
    return Manifest(
        artifacts=entries,
        config_freeze=freeze_hash(config or {}),
        created_at=stamp,
        environment=Environment.capture(repository_root, record_host=record_host).to_dict(),
        experiment_id=experiment_dir.name,
    )


def check(manifest: Manifest, experiment_dir: Path) -> CheckResult:
    """Compare a manifest against the artifacts on disk now."""
    experiment_dir = Path(experiment_dir)
    if not experiment_dir.is_dir():
        raise ManifestError(f"{experiment_dir} is not a directory")

    recorded = {entry.path: entry for entry in manifest.artifacts}
    present = {
        path.relative_to(experiment_dir).as_posix()
        for path in experiment_dir.rglob("*")
        if path.is_file() and path.name != "index.db"
    }

    missing, changed = [], []
    for relative, entry in sorted(recorded.items()):
        target = experiment_dir / relative
        if not target.is_file():
            missing.append(relative)
            continue
        if hash_file(target) != entry.sha256:
            changed.append(relative)

    return CheckResult(
        added=tuple(sorted(present - set(recorded))),
        changed=tuple(changed),
        checked=len(recorded),
        experiment_id=manifest.experiment_id,
        missing=tuple(missing),
    )
