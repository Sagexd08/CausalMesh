"""Import CooperBench tasks onto `TaskDefinition` (backlog §54).

CooperBench is a real, external benchmark for evaluating how well AI coding
agents cooperate on software-engineering tasks that carry a real risk of
conflict:

    "A benchmark for evaluating how well AI coding agents can cooperate on
    software engineering tasks with potential conflicts."
    — github.com/cooperbench/CooperBench (mirrored at
      github.com/hhh2210/CooperBench)

199 features across 30 tasks drawn from 12 open-source repositories
(Python, Go, Rust, JavaScript), forming 652 unique feature pairs. A task is
one upstream pull request split into between 2 and 12 features, and the
unit of work is a *pair* of them, implemented concurrently by two agents;
success is defined as both agents' patches merging cleanly *and* passing
their respective test suites — which is already a two-part,
automatically-decided criterion, the same shape §38 requires here.

**The raw dataset layout** this module reads, verified against a real
checkout of github.com/cooperbench/CooperBench (commit `63b9d44`, the
`dataset/` tree; counts in `docs/evidence/cooperbench-real-import.json`)::

    dataset/
      <repo_name>_task/            # e.g. pallets_click_task
        task<id>/                  # e.g. task2800
          setup.sh                 # names the upstream clone URL + BASE_COMMIT
          Dockerfile, runner.sh    # the container-era harness
          run_tests.sh             # container-era test runner, takes patch args
          combined.patch           # every feature landed, conflicts resolved
          feature<N>/              # N = 1..(2 to 12) in the real data
            feature.md             # feature description, sanitized from a real PR
            feature.patch          # golden/reference implementation diff
            tests.patch            # hidden tests for this feature
      subsets/, README.md, SPEC_AUDIT.md, gold_conflict_report.json  # not tasks

The sample this module was first written against assumed exactly two
features and did not say where the base repository comes from. Both were
wrong for the real data: see `feature_numbers`/`feature_pairs` and
`cooperbench_base`. The base repository is not in the dataset at all;
`setup.sh` and the `Dockerfile` name an upstream repository and a pinned
commit.

Harbor (github.com/harbor-framework/harbor, `adapters/cooperbench`) is a
second, independently designed mapping of the same dataset onto a generic
instance format, useful here only as a design reference — its
`instance_id` scheme (`cb-<repo>-t<task>-f<feature>-<pair>`, e.g.
`cb-jinja-t1621-f1-6`) is not reused verbatim.

## What this module does

`import_task` reads one pair of features (`features=(i, j)`, default
`(1, 2)`) of one `dataset/<repo>/task<id>/` directory and produces a
`TaskDefinition`, mapping the first feature to `agent_a` and the second to
`agent_b`, which matches this project's two-agent floor (§35). A task with
N features is N*(N-1)/2 separate imports, enumerated by `feature_pairs`;
`import_dataset(pairs="all")` and `import_dataset_report` do that sweep.

## Design decision 1: patch materialization happens in the loader, not at run time

A CooperBench feature is a real unified diff (`feature.patch`) against a
real upstream repository, not a literal file write. `agents/script.py`'s
`Action` DSL only carries literal `content` for `write`/`create` — there is
no `PATCH`/`APPLY_PATCH` action kind.

Two ways to close that gap were considered:

1. **A new `ActionKind.PATCH`** that applies a unified diff to a path at
   run time. This preserves "this really is a diff" fidelity, but it also
   means the mock agent's action executor would need to shell out to (or
   reimplement) `git apply`/`patch` while a run is in flight — a new
   runtime dependency and a new failure mode (a patch that does not apply
   cleanly against a fixture whose state has drifted), for a DSL that
   `definition.py`'s own module docstring says exists so that "tasks are
   data, not code": *"A task that could execute arbitrary Python would
   make 'the same task' unverifiable across machines, and the
   configuration hash (§33) would no longer pin what actually ran."* A
   patch applied at run time is not quite arbitrary code, but it is
   exactly the same shape of risk: what actually lands in the workspace
   would depend on the version of `git`/`patch` on the machine running the
   task, not solely on the YAML.
2. **Pre-materialize at import time** (chosen): the loader applies
   `feature.patch` (and `tests.patch`, when present) against a checked-out
   base repository once, while building the `TaskDefinition`, and bakes
   the resulting literal file content into ordinary `write` actions — the
   same action kind `schema_handler_widen` and `concurrent_edit_collision`
   already use. The shipped YAML is still pure data with no runtime patch
   application, so §33's reproducibility property is untouched: replaying
   the YAML on any machine produces the same workspace regardless of
   whether that machine has `git` or a compatible `patch` binary at all.

The cost of option 2 is fidelity: the YAML no longer visibly says "this
content came from a diff." That is recorded, not hidden — `import_task`
stamps `note: "materialized from feature.patch by the CooperBench loader"`
on every action it generates, and `ImportedFeature.patch_text` is kept
alongside the `TaskDefinition` (though not embedded in the YAML) so an
operator inspecting the import can always see the original diff that
produced the write.

## Design decision 2: contested paths are discovered, not assumed

`schema_handler_widen`'s coordination structure was authored by
construction — its docstring says so directly, and the backlog explains
why: "the task system (§35-38) had to exist and be proven on a task whose
coordination structure is known by construction before importing tasks
whose structure has to be discovered." CooperBench tasks are the opposite:
two features were selected because their originating PRs happened to touch
overlapping or dependent code, and *which* paths overlap has to be read
out of the two patches, not declared in advance.

`touched_paths` parses unified-diff headers (`--- a/path`, `+++ b/path`)
out of each feature's `feature.patch`, and `contested_paths` is the
intersection of the two features' touched-path sets. `AgentRole.owns` is
each feature's touched paths *minus* the contested set (paths only that
feature's patch touches); a path in the contested set is deliberately left
out of both roles' `owns`, mirroring how `concurrent_edit_collision`
excludes `src/config.py` from any single owner (see `runner.py`'s
`_integrate_workspaces`, which pulls a contested path from the signed
chain's last accepted writer rather than from an owner).

## Design decision 3: divergence has no single marker string for an import

`schema_handler_widen` and `concurrent_edit_collision` both have a hand-
picked `divergence_marker` — a literal string known in advance to be what
a *failed* coordination attempt leaves behind. CooperBench's own success
criterion is "both patches merge cleanly AND pass tests," which has no
equivalent scalar: there is no single string that means "feature2's change
silently clobbered feature1's" across an arbitrary pair of real-world
patches, because what a bad merge looks like depends on the two patches'
actual content.

This loader does **not** fabricate one. `divergence_file`/`divergence_marker`
are left `None` on an imported task unless the caller supplies them
explicitly (`ImportOptions.divergence_file`/`divergence_marker`), and
`ValidationIssue` code `incomplete_divergence_check` in `validation.py`
already treats "both given or neither" as the only valid shapes, so an
imported task with no marker validates as a task with *no divergence
check* rather than as a task with a fake one. `SuccessCriteria`'s own
docstring calls a subjective label forbidden for the primary outcome (§38)
— inventing a marker that is not really diagnostic would be exactly that,
dressed as objectivity. This is recorded as a limitation of the import,
not patched over: a task imported this way is judged on
`tests_passed` alone unless an operator supplies a real marker for that
specific pair by hand.

## No real dataset is vendored

No CooperBench files are checked into this repository. The loader's unit
tests run against a small SYNTHETIC sample at
`tests/fixtures/cooperbench_sample/` and against datasets built on the fly
in `tests/unit/test_cooperbench_real_layout.py`, each labeled synthetic and
none presented as real CooperBench content. The loader has also been run
over a real checkout: `scripts/cooperbench_real.py` does it, and its counts
are in `docs/evidence/cooperbench-real-import.json`.

## Pointing this at a real dataset

With a checkout of github.com/cooperbench/CooperBench (network is needed on
first use, to fetch each task's pinned upstream commit)::

    from pathlib import Path
    from causalmesh.tasks.cooperbench import (
        git_base_files_provider, import_dataset_report, import_task,
    )

    provider = git_base_files_provider(Path("/scratch/upstream-cache"))
    report = import_dataset_report(
        Path("/path/to/CooperBench/dataset"), pairs="all", base_files_provider=provider
    )
    print(report.succeeded, report.failed, report.failures_by_reason())

    task_dir = Path("/path/to/CooperBench/dataset/<repo>_task/task<id>")
    imported = import_task(
        task_dir, features=(1, 2), base_files=provider(task_dir, (1, 2))
    )
    imported.write_yaml(Path("tasks/cb_<repo>_task<id>.yaml"))

then run the existing §36/§37 machinery as for any hand-authored task. Two
things the real data adds that a hand-authored task does not have:

- the fixture for a *run* must be the whole base repository, not just the
  files the patches touch (`cooperbench_base.checkout_base_repo`), and the
  dataset's own `run_tests.sh` cannot be the integration test (it installs
  from the network and takes patch paths as arguments), so
  `ImportOptions(hidden_tests="pytest")` generates one. That harness is this
  loader's adaptation, not CooperBench's own, and it is Python-only.
- a contested path is resolved to one agent's whole file by
  `tasks/runner.py::_integrate_workspaces`, where CooperBench's own criterion
  is a `git merge` of the two patches. The two can disagree, and do; see
  `docs/backlog.md`, "CooperBench import (§54)".
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

from .cooperbench_base import BaseRepoError, base_files_for_paths, parse_base_spec
from .definition import AgentRole, SuccessCriteria, TaskDefinition, TaskError, TaskFamily

__all__ = [
    "BaseFilesProvider",
    "CooperBenchImportError",
    "ImportOptions",
    "ImportReport",
    "ImportedFeature",
    "ImportedTask",
    "PairOutcome",
    "feature_numbers",
    "feature_pairs",
    "git_base_files_provider",
    "import_dataset",
    "import_dataset_report",
    "import_task",
    "touched_paths",
]


class CooperBenchImportError(ValueError):
    """Raised when a CooperBench-shaped directory cannot be imported."""


def _read_text_exact(path: Path) -> str:
    """Read UTF-8 text without newline translation.

    `Path.read_text` folds CRLF into LF. A real repository's file may
    genuinely use CRLF, and a patch against it carries CRLF context lines,
    so folding them changes what `git apply` sees.
    """
    return path.read_bytes().decode("utf-8")


def _write_text_exact(path: Path, content: str) -> None:
    """Write UTF-8 text without newline translation.

    `Path.write_text` turns LF into CRLF on Windows, which would make the
    materialized content depend on the platform the import ran on.
    """
    path.write_bytes(content.encode("utf-8"))


_DIFF_PATH_PATTERN = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(\S+)")
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")


def touched_paths(patch_text: str) -> frozenset[str]:
    """Extract the set of paths a unified diff touches.

    Reads `--- a/<path>` / `+++ b/<path>` headers only — the portion of a
    unified diff format that is stable across `git diff`, `git format-patch`
    and plain `diff -u` output. `/dev/null` (a created or deleted file) is
    excluded, since it names no real path in either tree.

    Header lines are only recognised *outside* hunks. A hunk is consumed by
    its declared line counts (`@@ -a,b +c,d @@`), because a removed line
    whose content begins with `-- ` (an SQL or Lua comment, a YAML document
    marker) renders as `--- ...` inside the hunk and would otherwise be read
    as a file header naming a path that is not in the diff. Lines are split
    on newline only: `str.splitlines` also splits on form feed and other
    separators that can occur inside source lines, which would miscount a
    hunk.
    """
    paths: set[str] = set()
    old_left = new_left = 0
    lines = patch_text.split("\n")
    for index, line in enumerate(lines):
        if old_left > 0 or new_left > 0:
            following = lines[index + 1 : index + 3]
            opens_a_file = (
                line.startswith("--- ")
                and len(following) == 2
                and following[0].startswith("+++ ")
                and following[1].startswith("@@ ")
            )
            if opens_a_file:
                # `---`, `+++`, `@@` in a row is a file header even where the
                # declared counts say the hunk is still open: a miscounted
                # patch must not swallow the next file's header.
                old_left = new_left = 0
            else:
                marker = line[:1]
                if marker == "\\":  # "\ No newline at end of file" is not a counted line
                    continue
                if marker == " " or line == "":
                    old_left -= 1
                    new_left -= 1
                    continue
                if marker == "-" and old_left > 0:
                    old_left -= 1
                    continue
                if marker == "+" and new_left > 0:
                    new_left -= 1
                    continue
                # A line that cannot belong to the hunk: the counts were wrong
                # (a hand-edited patch). Stop trusting them and parse it as a header.
                old_left = new_left = 0
        hunk = _HUNK_HEADER.match(line)
        if hunk:
            old_left = int(hunk.group(1)) if hunk.group(1) is not None else 1
            new_left = int(hunk.group(2)) if hunk.group(2) is not None else 1
            continue
        match = _DIFF_PATH_PATTERN.match(line)
        if not match:
            continue
        candidate = match.group(1).strip()
        if candidate in ("", "/dev/null"):
            continue
        paths.add(candidate)
    return frozenset(paths)


def _read_text(path: Path) -> str:
    """Read UTF-8 text without translating line endings.

    `Path.read_text` applies universal-newline translation, which would turn
    a CRLF patch or a CRLF source file into LF and make the patch stop
    applying (or the materialized content stop matching the real file). The
    loader moves bytes, so it decodes bytes.
    """
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CooperBenchImportError(f"{path}: not valid UTF-8 ({exc})") from exc


def _write_text(path: Path, text: str) -> None:
    """Write UTF-8 text byte-for-byte (no `\\n` -> `\\r\\n` on Windows)."""
    path.write_bytes(text.encode("utf-8"))


@dataclass(frozen=True)
class ImportedFeature:
    """One CooperBench `featureN/` directory, read and parsed.

    `patch_text` and `tests_patch_text` are kept for inspection (an
    operator can always see the diff a write action was materialized
    from) even though the `TaskDefinition` itself never carries raw diff
    text — see the module docstring's "Design decision 1".
    """

    agent_id: str
    description: str
    patch_text: str
    tests_patch_text: str | None
    touched: frozenset[str]

    @classmethod
    def from_directory(cls, path: Path, *, agent_id: str) -> ImportedFeature:
        feature_md = path / "feature.md"
        feature_patch = path / "feature.patch"
        if not feature_patch.is_file():
            raise CooperBenchImportError(f"{path}: missing feature.patch")

        description = _read_text(feature_md) if feature_md.is_file() else ""
        patch_text = _read_text(feature_patch)

        tests_patch = path / "tests.patch"
        tests_patch_text = _read_text(tests_patch) if tests_patch.is_file() else None

        return cls(
            agent_id=agent_id,
            description=description,
            patch_text=patch_text,
            tests_patch_text=tests_patch_text,
            touched=touched_paths(patch_text),
        )


@dataclass(frozen=True)
class ImportOptions:
    """Knobs an operator may set when importing one CooperBench task.

    `divergence_file`/`divergence_marker` default to `None` deliberately —
    see the module docstring's "Design decision 3". A caller who has
    inspected a specific pair and can name a real marker may supply one;
    the loader never invents one on its own.
    """

    task_id: str | None = None
    version: str = "1.0.0"
    divergence_file: str | None = None
    divergence_marker: str | None = None
    test_runner: tuple[str, ...] = ("bash", "run_tests.sh")
    #: `"none"` (default) keeps the dataset's own `run_tests.sh`, which is a
    #: container-era script that installs dependencies from the network and
    #: takes patch paths as arguments; it is not runnable as a bare
    #: `bash run_tests.sh` inside a workspace. `"pytest"` generates a
    #: `run_tests.sh` that applies each feature's `tests.patch` to a scratch
    #: copy of the integrated workspace and runs the Python test files that
    #: patch touches, success being every feature's tests passing. That is an
    #: adaptation written by this loader, not CooperBench's own harness, and
    #: it is only meaningful when the fixture is the *whole* base repository
    #: (see `cooperbench_base.checkout_base_repo`), not just the touched files.
    hidden_tests: str = "none"
    #: How the integrated workspace resolves a path both features edit.
    #: `"last_writer"` (default) keeps whole-file, winner-take-all integration:
    #: one of two features that edit the same file is always lost, so 652 of
    #: 652 real pairs are contested and none can succeed on a contested file.
    #: `"three_way"` merges the two features' files against the base
    #: (`tasks/merge3.py`), which is the shape CooperBench itself scores: the
    #: edits must merge cleanly and pass. It changes the task's content hash.
    contested_merge: str = "last_writer"


@dataclass
class ImportedTask:
    """The result of importing one CooperBench task directory.

    Bundles the `TaskDefinition` with the base-repo file contents needed
    to build its execution fixture (`fixtures/<task_id>/`), so a caller can
    write both the task YAML and the fixture from one object rather than
    re-deriving the fixture from the source directory a second time.

    `feature_numbers` records which two of the task's `featureN/` directories
    this import used: a real CooperBench task has between 2 and 12 features,
    and each *pair* of them is a separate coordination problem.
    `extra_files` are additional fixture files the loader generated (the
    hidden-test patches for `hidden_tests="pytest"`).
    """

    definition: TaskDefinition
    repo_name: str
    source_task_id: str
    features: dict[str, ImportedFeature]
    base_files: dict[str, str]
    setup_sh: str | None
    run_tests_sh: str | None
    feature_numbers: tuple[int, int] = (1, 2)
    extra_files: dict[str, str] = field(default_factory=dict)

    def write_yaml(self, path: Path) -> Path:
        """Write the `TaskDefinition` as YAML in the shape `from_yaml` reads.

        Round-trips through `to_dict()` plus a header comment identifying
        the CooperBench provenance, matching the commented-header style
        `schema_handler_widen.yaml` and `concurrent_edit_collision.yaml`
        both use.
        """
        import yaml

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        first, second = self.feature_numbers
        header = (
            f"# Imported from CooperBench (backlog §54).\n"
            f"# Source: dataset/{self.repo_name}/{self.source_task_id}\n"
            f"# feature{first} -> agent_a, feature{second} -> agent_b.\n"
            f"# Generated by causalmesh.tasks.cooperbench.import_task; do not hand-edit\n"
            f"# the scenario actions -- edit the source CooperBench feature and re-import.\n"
        )
        body = yaml.safe_dump(self.definition.to_dict(), sort_keys=False, default_flow_style=False)
        _write_text(path, header + body)
        return path

    def write_fixture(self, root: Path) -> Path:
        """Write the base-repo fixture this task's agents run against.

        This is the pre-patch state — neither feature's patch has been
        applied yet — matching `fixtures/schema_handler/` and
        `fixtures/shared_config/`'s role as "the repository fixture" in
        `definition.py`'s module docstring. Both agents' scripted actions
        (materialized from `feature.patch`) apply their changes on top of
        this when the task runs.
        """
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        for relative, content in self.base_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_text(target, content)
        if self.setup_sh is not None:
            _write_text(root / "setup.sh", self.setup_sh)
        if self.run_tests_sh is not None:
            _write_text(root / "run_tests.sh", self.run_tests_sh)
        for relative, content in self.extra_files.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_text(target, content)
        return root


def _summarize(feature_md: str, *, limit: int = 200) -> str:
    """The first non-empty, non-heading line of a `feature.md`, for `AgentRole.description`.

    CooperBench's `feature.md` files typically open with a markdown `#
    Title` line, which makes a poor one-line summary on its own; this skips
    heading and blank lines and falls back to the heading itself only when
    nothing else is present.
    """
    lines = [line.strip() for line in feature_md.strip().splitlines() if line.strip()]
    for line in lines:
        if not line.startswith("#"):
            return line[:limit]
    return lines[0][:limit] if lines else ""


def _apply_patch(base_files: dict[str, str], patch_text: str, *, source: Path) -> dict[str, str]:
    """Apply one unified diff to an in-memory file map and return the result.

    Shells out to `git apply` against a throwaway worktree rather than
    hand-parsing hunks: a hand-rolled unified-diff applier is exactly the
    kind of "plausible but possibly wrong" logic AGENTS.md and this
    project's own backlog (see "Causal edges over the chain",
    `docs/backlog.md`) argue against building when a well-tested tool
    already does the job. This runs once, at import time, never inside a
    scripted run — see the module docstring's "Design decision 1".
    """
    import tempfile

    with tempfile.TemporaryDirectory(prefix="causalmesh_cooperbench_") as tmp:
        work = Path(tmp)
        for relative, content in base_files.items():
            target = work / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_text(target, content)

        patch_path = work / "_import.patch"
        _write_text(patch_path, patch_text)

        # `git init` only isolates the apply from any enclosing repository
        # (a TMPDIR inside a checkout would otherwise change what `git apply`
        # resolves paths against). Nothing is committed: `git apply` patches
        # the working tree and needs neither an index entry nor a commit.
        subprocess.run(["git", "init", "-q"], cwd=work, check=True, capture_output=True)

        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "apply", "--whitespace=nowarn", str(patch_path)],
            cwd=work,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise CooperBenchImportError(
                f"{source}: feature.patch did not apply cleanly against the base "
                f"repository state: {result.stderr.strip()}"
            )

        applied: dict[str, str] = {}
        for path in work.rglob("*"):
            if path.is_file() and ".git" not in path.parts and path.name != "_import.patch":
                relative = path.relative_to(work).as_posix()
                applied[relative] = _read_text(path)
        return applied


def feature_numbers(source: Path) -> tuple[int, ...]:
    """The feature numbers a task directory carries, ascending.

    A real CooperBench task is not two features: the 30 real tasks carry
    between 2 and 12 `featureN/` directories each (199 in all), and the
    benchmark's unit of work is a *pair* of them (652 pairs). Numbers are
    read from the directory names, not assumed contiguous.
    """
    source = Path(source)
    numbers: list[int] = []
    for child in source.iterdir():
        match = re.fullmatch(r"feature(\d+)", child.name)
        if match and child.is_dir():
            numbers.append(int(match.group(1)))
    return tuple(sorted(numbers))


def feature_pairs(source: Path) -> list[tuple[int, int]]:
    """Every unordered pair of a task's features, in ascending order."""
    return list(combinations(feature_numbers(source), 2))


def _python_test_files(tests_patch_text: str) -> list[str]:
    """Python test files a `tests.patch` adds or edits, sorted."""
    return sorted(
        path
        for path in touched_paths(tests_patch_text)
        if path.endswith(".py")
        and (
            Path(path).name.startswith("test_")
            or Path(path).name.endswith("_test.py")
            or "tests" in Path(path).parts
        )
    )


_PYTEST_HARNESS = """#!/usr/bin/env bash
# Generated by causalmesh.tasks.cooperbench (hidden_tests="pytest").
# NOT CooperBench's own run_tests.sh, which installs dependencies from the
# network and takes patch paths as arguments. This applies each feature's
# tests.patch to a scratch copy of the integrated workspace and runs the
# Python test files that patch touches. Success is every feature's tests
# passing, which is the shape of CooperBench's merged-pair criterion.
set -u
ROOT="$(pwd)"
export PYTHONPATH="$ROOT/src:$ROOT${PYTHONPATH:+:$PYTHONPATH}"
status=0
run_feature() {
  label="$1"; patch="$2"; shift 2
  scratch="$(mktemp -d)"
  cp -a "$ROOT/." "$scratch/ws"
  if ( cd "$scratch/ws" \\
       && git apply --ignore-whitespace --ignore-space-change "$patch" \\
       && python -m pytest -q -p no:cacheprovider -x "$@" ); then
    echo "$label: PASS"
  else
    echo "$label: FAIL"
    status=1
  fi
  rm -rf "$scratch"
}
"""


def _pytest_harness(tests: list[tuple[str, str, list[str]]]) -> str:
    """Render the generated `run_tests.sh`: one `run_feature` call per feature."""
    lines = [_PYTEST_HARNESS.rstrip("\n")]
    for label, patch_path, files in tests:
        quoted = " ".join(f"'{name}'" for name in files)
        lines.append(f"run_feature {label} '{patch_path}' {quoted}")
    lines.append("exit $status")
    return "\n".join(lines) + "\n"


def import_task(
    source: Path,
    *,
    features: tuple[int, int] = (1, 2),
    base_files: dict[str, str] | None = None,
    options: ImportOptions | None = None,
) -> ImportedTask:
    """Import one pair of features of a `dataset/<repo>/task<id>/` directory.

    `features` names which two `featureN/` directories become `agent_a` and
    `agent_b`; the default `(1, 2)` is the pair this loader always used. A
    real task has more than two features (see `feature_numbers`), and each
    pair is a distinct import.

    `base_files` is the pre-patch repository state as `{relative_path:
    content}`. When omitted, this loader treats the base state as empty
    (every path either feature touches is presumed newly created) — correct
    for a synthetic fixture built from scratch, and the caller's
    responsibility to supply for a real checkout. The real dataset does not
    ship the base repository: `setup.sh` names an upstream clone URL and a
    pinned commit (see `cooperbench_base`), which `git_base_files_provider`
    resolves. `setup.sh` itself is read, never executed (running an unknown
    shell script from imported data at import time would be the same
    "arbitrary code" risk `definition.py`'s docstring warns tasks themselves
    must not carry).
    """
    source = Path(source)
    if not source.is_dir():
        raise CooperBenchImportError(f"{source}: not a directory")

    first, second = features
    if first == second or first < 1 or second < 1:
        raise CooperBenchImportError(f"{source}: features must be two distinct positive numbers")
    feature1_dir = source / f"feature{first}"
    feature2_dir = source / f"feature{second}"
    if not feature1_dir.is_dir() or not feature2_dir.is_dir():
        raise CooperBenchImportError(
            f"{source}: expected feature{first}/ and feature{second}/ subdirectories"
        )

    options = options or ImportOptions()
    if options.hidden_tests not in ("none", "pytest"):
        raise CooperBenchImportError(f"unknown hidden_tests mode {options.hidden_tests!r}")
    base_files = dict(base_files or {})

    feature_a = ImportedFeature.from_directory(feature1_dir, agent_id="agent_a")
    feature_b = ImportedFeature.from_directory(feature2_dir, agent_id="agent_b")

    contested = feature_a.touched & feature_b.touched
    owns_a = feature_a.touched - contested
    owns_b = feature_b.touched - contested

    materialized_a = _apply_patch(base_files, feature_a.patch_text, source=feature1_dir)
    materialized_b = _apply_patch(base_files, feature_b.patch_text, source=feature2_dir)

    repo_name = source.parent.name
    source_task_id = source.name
    default_id = f"cb_{repo_name}_{source_task_id}"
    if (first, second) != (1, 2):
        default_id = f"{default_id}_f{first}_{second}"
    task_id = options.task_id or default_id.replace("-", "_")

    def _actions_for(
        feature: ImportedFeature, materialized: dict[str, str]
    ) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        for path in sorted(feature.touched):
            content = materialized.get(path)
            if content is None:
                # Deleted by the patch relative to base_files; nothing to
                # write, and this loader does not emit `delete` actions
                # speculatively for content it never actually saw.
                continue
            actions.append(
                {
                    "write": {
                        "path": path,
                        "content": content,
                        "note": "materialized from feature.patch by the CooperBench loader",
                    }
                }
            )
        return actions

    scenario = {
        "agent_a": {
            "owns": sorted(owns_a),
            "actions": [{"read": path} for path in sorted(feature_a.touched & feature_b.touched)]
            + _actions_for(feature_a, materialized_a),
        },
        "agent_b": {
            "owns": sorted(owns_b),
            "depends_on": sorted(contested),
            "actions": [{"read": path} for path in sorted(feature_a.touched & feature_b.touched)]
            + [{"wait": "1s"}]
            + _actions_for(feature_b, materialized_b),
        },
    }

    roles = (
        AgentRole(
            agent_id="agent_a",
            owns=owns_a,
            description=_summarize(feature_a.description),
        ),
        AgentRole(
            agent_id="agent_b",
            owns=owns_b,
            depends_on=contested,
            description=_summarize(feature_b.description),
        ),
    )

    success = SuccessCriteria(
        integration_test=options.test_runner,
        divergence_file=options.divergence_file,
        divergence_marker=options.divergence_marker,
    )

    definition = TaskDefinition(
        task_id=task_id,
        version=options.version,
        family=TaskFamily.COOPERBENCH_IMPORT,
        description=(
            f"Imported from CooperBench {repo_name}/{source_task_id} "
            f"(features {first} and {second}): two "
            "independently-authored features implemented concurrently, "
            "with contested paths discovered from their patches rather "
            "than declared by construction."
        ),
        fixture=task_id,
        roles=roles,
        scenario=scenario,
        success=success,
        contested_paths=contested,
        contested_merge=options.contested_merge,
    )

    setup_sh_path = source / "setup.sh"
    run_tests_sh_path = source / "run_tests.sh"
    run_tests_sh = _read_text(run_tests_sh_path) if run_tests_sh_path.is_file() else None
    extra_files: dict[str, str] = {}

    if options.hidden_tests == "pytest":
        harness_inputs: list[tuple[str, str, list[str]]] = []
        for number, feature in ((first, feature_a), (second, feature_b)):
            if feature.tests_patch_text is None:
                raise CooperBenchImportError(f"{source}: feature{number} has no tests.patch")
            test_files = _python_test_files(feature.tests_patch_text)
            if not test_files:
                raise CooperBenchImportError(
                    f"{source}: feature{number}'s tests.patch touches no Python test file, "
                    'so hidden_tests="pytest" has nothing to run'
                )
            patch_name = f".cooperbench/feature{number}_tests.patch"
            extra_files[patch_name] = feature.tests_patch_text
            harness_inputs.append((f"feature{number}", patch_name, test_files))
        run_tests_sh = _pytest_harness(harness_inputs)

    return ImportedTask(
        definition=definition,
        repo_name=repo_name,
        source_task_id=source_task_id,
        features={"agent_a": feature_a, "agent_b": feature_b},
        base_files=base_files,
        setup_sh=_read_text(setup_sh_path) if setup_sh_path.is_file() else None,
        run_tests_sh=run_tests_sh,
        feature_numbers=(first, second),
        extra_files=extra_files,
    )


#: Supplies the pre-patch base files for one pair of one task:
#: `(task_directory, (feature_a, feature_b)) -> {path: content}`.
BaseFilesProvider = Callable[[Path, tuple[int, int]], dict[str, str]]


def git_base_files_provider(cache_dir: Path) -> BaseFilesProvider:
    """A provider that reads the base files from the task's pinned upstream commit.

    Reads `setup.sh` for the clone URL and `BASE_COMMIT` (text only, never
    executed), then fetches just the files the pair's two `feature.patch`
    files touch. Needs network the first time a commit is seen; `cache_dir`
    makes repeat reads offline. Raises `BaseRepoError` on any failure to
    resolve or fetch, which `import_dataset_report` records as a
    `base_repo` failure.
    """
    cache_dir = Path(cache_dir)

    def provide(task_dir: Path, pair: tuple[int, int]) -> dict[str, str]:
        setup = task_dir / "setup.sh"
        if not setup.is_file():
            raise BaseRepoError(f"{task_dir}: no setup.sh to name the base repository")
        spec = parse_base_spec(_read_text(setup))
        paths: set[str] = set()
        for number in pair:
            patch = task_dir / f"feature{number}" / "feature.patch"
            if not patch.is_file():
                raise BaseRepoError(f"{task_dir}: feature{number} has no feature.patch")
            paths |= touched_paths(_read_text(patch))
        return base_files_for_paths(spec, paths, cache_dir=cache_dir)

    return provide


def _task_directories(dataset_root: Path) -> list[Path]:
    """Every `<repo>/task<id>/` directory under a dataset root.

    Only directories named `task<digits>` count as tasks, so the real
    dataset's own non-task entries (`subsets/`, `README.md`, the audit
    files) are never mistaken for repositories or tasks.
    """
    tasks: list[Path] = []
    for repo_dir in sorted(p for p in dataset_root.iterdir() if p.is_dir()):
        tasks.extend(
            sorted(p for p in repo_dir.iterdir() if p.is_dir() and re.fullmatch(r"task\d+", p.name))
        )
    return tasks


def _pairs_to_import(task_dir: Path, pairs: str) -> list[tuple[int, int]]:
    if pairs == "first":
        return [(1, 2)]
    if pairs == "all":
        return feature_pairs(task_dir)
    raise CooperBenchImportError(f"pairs must be 'first' or 'all', not {pairs!r}")


def import_dataset(
    dataset_root: Path,
    *,
    pairs: str = "first",
    base_files_by_task: dict[str, dict[str, str]] | None = None,
    base_files_provider: BaseFilesProvider | None = None,
    options: ImportOptions | None = None,
) -> list[ImportedTask]:
    """Import every `<repo>/task<id>/` directory under a CooperBench dataset root.

    `pairs="first"` (default) imports each task's `(feature1, feature2)`
    pair, as this function always did; `pairs="all"` imports every feature
    pair of every task. Base files come from `base_files_by_task`
    (`"<repo>/<task>"` keys, used for every pair of that task) or, failing
    that, `base_files_provider`.

    A malformed task directory raises rather than being skipped, matching
    `load_tasks`'s discipline in `validation.py`: silently omitting a task
    would change the imported suite's composition without anyone noticing.
    `import_dataset_report` is the variant that records failures instead of
    raising, for a run over data that is not known to be clean.
    """
    dataset_root = Path(dataset_root)
    if not dataset_root.is_dir():
        raise CooperBenchImportError(f"{dataset_root}: not a directory")

    base_files_by_task = base_files_by_task or {}
    imported: list[ImportedTask] = []
    for task_dir in _task_directories(dataset_root):
        key = f"{task_dir.parent.name}/{task_dir.name}"
        for pair in _pairs_to_import(task_dir, pairs):
            base = base_files_by_task.get(key)
            if base is None and base_files_provider is not None:
                base = base_files_provider(task_dir, pair)
            imported.append(import_task(task_dir, features=pair, base_files=base, options=options))
    return imported


@dataclass(frozen=True)
class PairOutcome:
    """What happened when one feature pair was imported: a success or a named failure.

    `stage` names where a failure happened, so the reasons can be counted
    rather than pooled under "failed": `base_repo` (the pinned upstream
    commit could not be determined or fetched), `import` (the directory or
    a patch is unusable: a patch that does not apply, a missing file),
    `definition` (the resulting `TaskDefinition` was refused), or
    `unexpected` (an exception this loader did not anticipate, recorded
    with its type rather than swallowed).
    """

    repo: str
    task: str
    features: tuple[int, int]
    status: str
    task_id: str | None = None
    stage: str | None = None
    reason: str | None = None
    contested_paths: tuple[str, ...] = ()
    files_touched: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "contested_paths": list(self.contested_paths),
            "features": list(self.features),
            "files_touched": self.files_touched,
            "reason": self.reason,
            "repo": self.repo,
            "stage": self.stage,
            "status": self.status,
            "task": self.task,
            "task_id": self.task_id,
        }


@dataclass
class ImportReport:
    """Every pair attempted, with its outcome. Nothing is omitted."""

    outcomes: list[PairOutcome]
    imported: list[ImportedTask] = field(default_factory=list)

    @property
    def attempted(self) -> int:
        return len(self.outcomes)

    @property
    def succeeded(self) -> int:
        return sum(1 for o in self.outcomes if o.status == "imported")

    @property
    def failed(self) -> int:
        return self.attempted - self.succeeded

    def failures_by_reason(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for outcome in self.outcomes:
            if outcome.status != "imported":
                key = f"{outcome.stage}: {outcome.reason}"
                counts[key] = counts.get(key, 0) + 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        tasks = {(o.repo, o.task) for o in self.outcomes}
        ok_tasks = {(o.repo, o.task) for o in self.outcomes if o.status == "imported"}
        return {
            "attempted_pairs": self.attempted,
            "failed_pairs": self.failed,
            "failures_by_reason": self.failures_by_reason(),
            "imported_pairs": self.succeeded,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "tasks_attempted": len(tasks),
            "tasks_with_at_least_one_imported_pair": len(ok_tasks),
        }


def import_dataset_report(
    dataset_root: Path,
    *,
    pairs: str = "all",
    base_files_provider: BaseFilesProvider | None = None,
    options: ImportOptions | None = None,
    keep_tasks: bool = False,
) -> ImportReport:
    """Import a dataset and account for every pair, failures included.

    Unlike `import_dataset`, a pair that cannot be imported does not stop
    the run and is not dropped: it becomes a `PairOutcome` with a `stage`
    and a `reason`. `keep_tasks=True` also keeps each `ImportedTask` (they
    carry the materialized file contents, so a full run holds a lot of
    text); by default only the outcomes are kept.

    Only the exceptions this loader raises on purpose are classified by
    stage. Anything else is recorded as `unexpected` with its type, rather
    than being allowed to abort a long run or, worse, to vanish.
    """
    dataset_root = Path(dataset_root)
    if not dataset_root.is_dir():
        raise CooperBenchImportError(f"{dataset_root}: not a directory")

    outcomes: list[PairOutcome] = []
    kept: list[ImportedTask] = []
    for task_dir in _task_directories(dataset_root):
        repo, task = task_dir.parent.name, task_dir.name
        for pair in _pairs_to_import(task_dir, pairs):
            try:
                base = base_files_provider(task_dir, pair) if base_files_provider else None
                imported = import_task(task_dir, features=pair, base_files=base, options=options)
            except BaseRepoError as exc:
                outcomes.append(
                    PairOutcome(repo, task, pair, "failed", None, "base_repo", str(exc))
                )
            except CooperBenchImportError as exc:
                outcomes.append(PairOutcome(repo, task, pair, "failed", None, "import", str(exc)))
            except TaskError as exc:
                outcomes.append(
                    PairOutcome(repo, task, pair, "failed", None, "definition", str(exc))
                )
            except Exception as exc:  # noqa: BLE001 - recorded with its type, never swallowed
                outcomes.append(
                    PairOutcome(
                        repo,
                        task,
                        pair,
                        "failed",
                        None,
                        "unexpected",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
            else:
                outcomes.append(
                    PairOutcome(
                        repo,
                        task,
                        pair,
                        "imported",
                        task_id=imported.definition.task_id,
                        contested_paths=tuple(sorted(imported.definition.contested_paths)),
                        files_touched=len(
                            imported.features["agent_a"].touched
                            | imported.features["agent_b"].touched
                        ),
                    )
                )
                if keep_tasks:
                    kept.append(imported)
    return ImportReport(outcomes=outcomes, imported=kept)
