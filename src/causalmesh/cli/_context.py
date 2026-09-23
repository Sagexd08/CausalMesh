"""Locating the repository and its data from wherever the CLI was invoked.

The commands share one notion of "where things are" so that `run` and
`verify` cannot disagree about which directory holds the raw data. Paths
are resolved once, here, and passed around as a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MARKERS = ("pyproject.toml", "tasks", "fixtures")


def find_root(start: Path | None = None) -> Path | None:
    """Walk upward looking for a CausalMesh checkout.

    Returns None rather than raising: a missing root is a normal condition
    for `doctor`, which exists precisely to report it.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in _MARKERS):
            return candidate
    return None


@dataclass(frozen=True)
class Repo:
    """Where everything lives for one invocation."""

    root: Path

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def fixtures_dir(self) -> Path:
        return self.root / "fixtures"

    @property
    def raw_dir(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def workspace_dir(self) -> Path:
        return self.root / "data" / "work"

    def experiment_dir(self, experiment_id: str) -> Path:
        return self.raw_dir / experiment_id

    def index_path(self, experiment_id: str) -> Path:
        return self.experiment_dir(experiment_id) / "index.db"

    def experiments(self) -> list[str]:
        """Every experiment that has produced data, newest first.

        Ordered by modification time because the question a caller is
        actually asking — as `--latest` does — is "which one did I just
        run", not "which sorts last".
        """
        if not self.raw_dir.is_dir():
            return []
        directories = [p for p in self.raw_dir.iterdir() if p.is_dir()]
        directories.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return [p.name for p in directories]

    def run_dirs(self, experiment_id: str) -> list[Path]:
        """The run directories of one experiment, in plan order.

        Sorted by name: run ids end in a zero-padded repetition, so the
        lexical order is the plan order.
        """
        experiment = self.experiment_dir(experiment_id)
        if not experiment.is_dir():
            return []
        return sorted(p for p in experiment.iterdir() if p.is_dir() and (p / "run.json").is_file())
