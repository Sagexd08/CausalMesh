"""Import CooperBench tasks onto `TaskDefinition` (backlog §54).

CooperBench is a real, external benchmark for evaluating how well AI coding
agents cooperate on software-engineering tasks that carry a real risk of
conflict:

    "A benchmark for evaluating how well AI coding agents can cooperate on
    software engineering tasks with potential conflicts."
    — github.com/cooperbench/CooperBench (mirrored at
      github.com/hhh2210/CooperBench)

199 features across 30 tasks drawn from 12 open-source repositories
(Python, Go, Rust, JavaScript), forming 652 unique feature pairs. Each task
pairs two features from the same repository that must be implemented
concurrently by two agents; success is defined as both agents' patches
merging cleanly *and* passing their respective test suites — which is
already a two-part, automatically-decided criterion, the same shape §38
requires here.

**The raw dataset layout** this module reads (as documented upstream, not
reproduced from a local checkout — see "No real dataset is vendored"
below)::

    dataset/
      <repo_name>/
        task<id>/
          setup.sh          # repository setup script
          run_tests.sh      # test runner script
          feature1/
            feature.md      # feature description, sanitized from a real PR
            feature.patch   # golden/reference implementation diff
            tests.patch     # test cases for this feature
          feature2/
            feature.md
            feature.patch
            tests.patch

Harbor (github.com/harbor-framework/harbor, `adapters/cooperbench`) is a
second, independently designed mapping of the same dataset onto a generic
instance format, useful here only as a design reference — its
`instance_id` scheme (`cb-<repo>-t<task>-f<feature>-<pair>`, e.g.
`cb-jinja-t1621-f1-6`) is not reused verbatim, but the read of the upstream
layout above was cross-checked against it.

## What this module does

`import_task` reads one `dataset/<repo>/task<id>/` directory and produces a
`TaskDefinition`, mapping CooperBench's own two-feature structure directly
onto this project's two-agent minimum — `feature1` -> `agent_a`, `feature2`
-> `agent_b`. No scaling decision is needed: CooperBench tasks are exactly
two-agent by construction, same as `TaskDefinition`'s floor (§35).

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

This sandbox has no network access to clone
`github.com/cooperbench/CooperBench`, and no CooperBench files are checked
into this repository. `import_task`/`import_dataset` are built and tested
against a small SYNTHETIC fixture at
`tests/fixtures/cooperbench_sample/` — a hand-written, clearly-labeled
stand-in with two tiny fake features and real small unified diffs against
a tiny fake repo — never presented as real CooperBench content. See
`tests/fixtures/cooperbench_sample/README.md`.

## Pointing this at a real dataset

Once a real CooperBench checkout exists on a machine that has one::

    from pathlib import Path
    from causalmesh.tasks.cooperbench import import_task, ImportOptions

    imported = import_task(
        Path("/path/to/CooperBench/dataset/<repo>/task<id>"),
        options=ImportOptions(task_id="cb_<repo>_task<id>"),
    )
    imported.write_yaml(Path("tasks/cb_<repo>_task<id>.yaml"))
    imported.write_fixture(Path("fixtures/cb_<repo>_task<id>"))

then run the existing §36/§37 machinery exactly as for any hand-authored
task — `validate_structure(imported.definition, fixtures_root=...)` and
`check_sensitivity(imported.definition, ...)`. Nothing about those two
gates is CooperBench-specific; this loader's only job is to produce a
`TaskDefinition` and a fixture directory that satisfy the same contracts
every other task already does. Batch-importing all 30 tasks / 652 pairs
is `import_dataset` iterating `dataset/*/task*/`, which this module
supports, but doing so against the real data has not happened — see
`docs/backlog.md`, "CooperBench import (§54)".
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .definition import AgentRole, SuccessCriteria, TaskDefinition, TaskFamily

__all__ = [
    "CooperBenchImportError",
    "ImportOptions",
    "ImportedFeature",
    "ImportedTask",
    "import_dataset",
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


def touched_paths(patch_text: str) -> frozenset[str]:
    """Extract the set of paths a unified diff touches.

    Reads `--- a/<path>` / `+++ b/<path>` headers only — the portion of a
    unified diff format that is stable across `git diff`, `git format-patch`
    and plain `diff -u` output. `/dev/null` (a created or deleted file) is
    excluded, since it names no real path in either tree.
    """
    paths: set[str] = set()
    for line in patch_text.splitlines():
        match = _DIFF_PATH_PATTERN.match(line)
        if not match:
            continue
        candidate = match.group(1).strip()
        if candidate in ("", "/dev/null"):
            continue
        paths.add(candidate)
    return frozenset(paths)


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

        description = _read_text_exact(feature_md) if feature_md.is_file() else ""
        patch_text = _read_text_exact(feature_patch)

        tests_patch = path / "tests.patch"
        tests_patch_text = _read_text_exact(tests_patch) if tests_patch.is_file() else None

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


@dataclass
class ImportedTask:
    """The result of importing one CooperBench task directory.

    Bundles the `TaskDefinition` with the base-repo file contents needed
    to build its execution fixture (`fixtures/<task_id>/`), so a caller can
    write both the task YAML and the fixture from one object rather than
    re-deriving the fixture from the source directory a second time.
    """

    definition: TaskDefinition
    repo_name: str
    source_task_id: str
    features: dict[str, ImportedFeature]
    base_files: dict[str, str]
    setup_sh: str | None
    run_tests_sh: str | None

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
        header = (
            f"# Imported from CooperBench (backlog §54).\n"
            f"# Source: dataset/{self.repo_name}/{self.source_task_id}\n"
            f"# feature1 -> agent_a, feature2 -> agent_b.\n"
            f"# Generated by causalmesh.tasks.cooperbench.import_task; do not hand-edit\n"
            f"# the scenario actions -- edit the source CooperBench feature and re-import.\n"
        )
        body = yaml.safe_dump(self.definition.to_dict(), sort_keys=False, default_flow_style=False)
        path.write_text(header + body, encoding="utf-8")
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
            _write_text_exact(target, content)
        if self.setup_sh is not None:
            _write_text_exact(root / "setup.sh", self.setup_sh)
        if self.run_tests_sh is not None:
            _write_text_exact(root / "run_tests.sh", self.run_tests_sh)
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
            _write_text_exact(target, content)

        patch_path = work / "_import.patch"
        _write_text_exact(patch_path, patch_text)

        subprocess.run(["git", "init", "-q"], cwd=work, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=import@causalmesh.local", "-c", "user.name=causalmesh"],
            cwd=work,
            check=False,
            capture_output=True,
        )
        subprocess.run(["git", "add", "-A"], cwd=work, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=import@causalmesh.local",
                "-c",
                "user.name=causalmesh",
                "commit",
                "-q",
                "-m",
                "base",
                "--allow-empty",
            ],
            cwd=work,
            check=True,
            capture_output=True,
        )

        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", str(patch_path)],
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
                applied[relative] = path.read_bytes().decode("utf-8", errors="replace")
        return applied


def import_task(
    source: Path,
    *,
    base_files: dict[str, str] | None = None,
    options: ImportOptions | None = None,
) -> ImportedTask:
    """Import one `dataset/<repo>/task<id>/` directory into a `TaskDefinition`.

    `base_files` is the pre-patch repository state as `{relative_path:
    content}`. When omitted, this loader treats the base state as empty
    (every path either feature touches is presumed newly created) — correct
    for a synthetic fixture built from scratch, and the caller's
    responsibility to supply for a real checkout, since `setup.sh` may do
    arbitrary environment preparation this loader does not execute (running
    an unknown shell script from imported data at import time would be the
    same "arbitrary code" risk `definition.py`'s docstring warns tasks
    themselves must not carry).
    """
    source = Path(source)
    if not source.is_dir():
        raise CooperBenchImportError(f"{source}: not a directory")

    feature1_dir = source / "feature1"
    feature2_dir = source / "feature2"
    if not feature1_dir.is_dir() or not feature2_dir.is_dir():
        raise CooperBenchImportError(f"{source}: expected feature1/ and feature2/ subdirectories")

    options = options or ImportOptions()
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
    task_id = options.task_id or f"cb_{repo_name}_{source_task_id}".replace("-", "_")

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
            f"Imported from CooperBench {repo_name}/{source_task_id}: two "
            "independently-authored features implemented concurrently, "
            "with contested paths discovered from their patches rather "
            "than declared by construction."
        ),
        fixture=task_id,
        roles=roles,
        scenario=scenario,
        success=success,
        contested_paths=contested,
    )

    setup_sh_path = source / "setup.sh"
    run_tests_sh_path = source / "run_tests.sh"

    return ImportedTask(
        definition=definition,
        repo_name=repo_name,
        source_task_id=source_task_id,
        features={"agent_a": feature_a, "agent_b": feature_b},
        base_files=base_files,
        setup_sh=_read_text_exact(setup_sh_path) if setup_sh_path.is_file() else None,
        run_tests_sh=_read_text_exact(run_tests_sh_path) if run_tests_sh_path.is_file() else None,
    )


def import_dataset(
    dataset_root: Path,
    *,
    base_files_by_task: dict[str, dict[str, str]] | None = None,
    options: ImportOptions | None = None,
) -> list[ImportedTask]:
    """Import every `<repo>/task<id>/` directory under a CooperBench dataset root.

    A malformed task directory raises rather than being skipped, matching
    `load_tasks`'s discipline in `validation.py`: silently omitting a task
    would change the imported suite's composition without anyone noticing.
    """
    dataset_root = Path(dataset_root)
    if not dataset_root.is_dir():
        raise CooperBenchImportError(f"{dataset_root}: not a directory")

    base_files_by_task = base_files_by_task or {}
    imported: list[ImportedTask] = []
    for repo_dir in sorted(p for p in dataset_root.iterdir() if p.is_dir()):
        for task_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
            key = f"{repo_dir.name}/{task_dir.name}"
            imported.append(
                import_task(
                    task_dir,
                    base_files=base_files_by_task.get(key),
                    options=options,
                )
            )
    return imported
