"""Batch import of the real CooperBench dataset, with the section-37 gate (backlog section 54).

`cooperbench.import_task` turns one two-feature directory into a task. The
real dataset is shaped differently from that call's input in three ways, and
this module is the layer that closes each gap without changing the importer:

1. **A real task has N features, not two.** The 30 tasks carry 199 features
   and form 652 unordered feature pairs. Every pair becomes its own imported
   task, `feature<i>` -> `agent_a` and `feature<j>` -> `agent_b` with
   `i < j`, staged into a scratch directory shaped the way `import_task`
   reads.
2. **The base repository is not in the dataset.** Each task names its
   repository and pre-patch commit in its `Dockerfile` (and again in
   `setup.sh`). `GitBaseResolver` fetches exactly that commit, shallow and
   without blobs, into a cache directory outside git, then reads only the
   files the task's patches touch. The resulting fixture is therefore a
   SPARSE slice of the repository (the touched files), not a full checkout.
3. **The dataset's `run_tests.sh` cannot be the success test here.** It
   needs a network, a language toolchain per repository (Python, Go, Rust,
   JavaScript), `uv` installs, and a directory named `agent_workspace`; it
   runs third-party code. This module never executes it. The success test
   it installs instead is an offline line-multiset oracle, described next.

## The success oracle, and what it is not

For every path either feature touches, the expected final file is "the base
file plus feature A's line changes plus feature B's line changes", compared
as a multiset of normalized lines (CR removed, trailing whitespace removed,
blank lines dropped). The fixture ships `cb_expected.json` (a digest per
path) and `cb_verify.py` (stdlib only); `run_tests.sh` runs the verifier in
the integrated workspace and exits non-zero on any mismatch.

That checks "both features' changes are present in the merged tree and
nothing else changed", which is what a clean merge of the two patches
produces. It is NOT the CooperBench hidden tests, it does not execute any
code from the target repository, and it says nothing about whether a
feature behaves correctly. A path deleted by either patch is excluded from
the check (the importer emits no delete action); the count is recorded.

## What a verdict means

Every run is a deterministic scripted mock agent replaying the golden
patches. The platform's contested-path merge (`runner._integrate_workspaces`)
is winner-take-all: a path both features touch comes from whichever agent
wrote it last, so the other feature's changes on that path are lost under
both C0 and C2. A pair with contested paths therefore fails the oracle in
both arms and the gate reports NOT SENSITIVE. That is a property of this
platform's merge, reported as data. Nothing here measures real agent
coordination.

## Failure isolation and resumability

Each pair is processed inside its own `try`; an exception becomes a `failed`
record with a stage and a reason, and the batch continues. A record is
appended to `results.jsonl` the moment a pair finishes, so an interrupted
run resumes: pairs already holding a terminal status (a verdict, or a
deliberate skip) are not redone unless `force` is set; `failed` pairs are
retried. `results.json` is rebuilt from the JSONL at the end.

Absent is `unknown`, never zero: fields that could not be determined (a
dataset commit outside a git checkout, for instance) are the string
`"unknown"`.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .cooperbench import CooperBenchImportError, ImportedTask, ImportOptions, import_task
from .definition import TaskDefinition
from .validation import check_sensitivity, validate_structure

__all__ = [
    "BINARY",
    "BaseResolutionError",
    "BaseResolver",
    "BaseSpec",
    "BatchOptions",
    "GitBaseResolver",
    "PairKey",
    "discover_pairs",
    "expected_digests",
    "line_digest",
    "parse_base_spec",
    "process_pair",
    "run_batch",
    "summarize",
]

NULL_STATUS = "unknown"

TERMINAL_STATUSES = frozenset({"sensitive", "not_sensitive", "skipped"})

DEFAULT_SEED = b"cooperbench-batch-import-seed"

_FEATURE_DIR = re.compile(r"^feature(\d+)$")
_SHA = re.compile(r"\b([0-9a-f]{40})\b")


class BaseResolutionError(RuntimeError):
    """The pre-patch base state of a task could not be obtained."""


class _Binary:
    """Marker for a base file that is not UTF-8 text."""

    def __repr__(self) -> str:
        return "BINARY"


BINARY = _Binary()

BaseFile = str | None | _Binary


@dataclass(frozen=True)
class BaseSpec:
    """Where a task's pre-patch repository state comes from."""

    repo_url: str
    commit: str

    def to_dict(self) -> dict[str, str]:
        return {"commit": self.commit, "repo_url": self.repo_url}


class BaseResolver(Protocol):
    """Reads files of one repository at one commit.

    A path absent at that commit maps to `None` (a file the patch creates).
    A file that is not UTF-8 text maps to `BINARY`. Anything that stops the
    read altogether raises `BaseResolutionError`.
    """

    def read_files(self, spec: BaseSpec, paths: Iterable[str]) -> dict[str, BaseFile]: ...


@dataclass(frozen=True, order=True)
class PairKey:
    """One feature pair of one task, `first < second`."""

    repo: str
    task: str
    first: int
    second: int

    @property
    def pair_id(self) -> str:
        return f"{self.repo}/{self.task}/f{self.first}-f{self.second}"

    @property
    def task_dir_name(self) -> str:
        return f"{self.repo}/{self.task}"

    @property
    def task_id(self) -> str:
        repo = self.repo[: -len("_task")] if self.repo.endswith("_task") else self.repo
        return f"cb_{repo}_{self.task}_f{self.first}_f{self.second}".replace("-", "_")


@dataclass(frozen=True)
class BatchOptions:
    """How one batch run behaves."""

    dataset_dir: Path
    output_dir: Path
    seed: bytes = DEFAULT_SEED
    repetitions: int = 1
    only_repos: frozenset[str] = frozenset()
    only_tasks: frozenset[str] = frozenset()
    max_pairs: int | None = None
    force: bool = False
    keep_workspaces: bool = False
    jobs: int = 1


# ---------------------------------------------------------------------------
# Dataset layout
# ---------------------------------------------------------------------------


def resolve_dataset_dir(path: Path) -> Path:
    """Accept either a CooperBench checkout root or its `dataset/` directory."""
    path = Path(path)
    if (path / "dataset").is_dir():
        return path / "dataset"
    return path


def _feature_numbers(task_dir: Path) -> list[int]:
    numbers = []
    for child in task_dir.iterdir():
        match = _FEATURE_DIR.match(child.name)
        if match and child.is_dir():
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def discover_pairs(options: BatchOptions) -> list[PairKey]:
    """Every unordered feature pair of every task under the dataset directory."""
    dataset = resolve_dataset_dir(options.dataset_dir)
    if not dataset.is_dir():
        raise CooperBenchImportError(f"{dataset}: not a directory")
    pairs: list[PairKey] = []
    for repo_dir in sorted(p for p in dataset.iterdir() if p.is_dir()):
        if options.only_repos and repo_dir.name not in options.only_repos:
            continue
        for task_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
            if not task_dir.name.startswith("task"):
                continue
            if options.only_tasks and task_dir.name not in options.only_tasks:
                continue
            numbers = _feature_numbers(task_dir)
            for index, first in enumerate(numbers):
                for second in numbers[index + 1 :]:
                    pairs.append(PairKey(repo_dir.name, task_dir.name, first, second))
    if options.max_pairs is not None:
        pairs = pairs[: options.max_pairs]
    return pairs


def check_checkout_line_endings(dataset: Path) -> None:
    """Refuse a checkout whose patches were rewritten to CRLF.

    Git for Windows defaults to `core.autocrlf=true`, which rewrites every
    text file in a clone, patches included; a CRLF patch no longer applies
    to an LF blob. A `diff --git` header line never legitimately ends in CR,
    so seeing one means the checkout, not the patch, is wrong.
    """
    for patch in sorted(Path(dataset).glob("*/task*/feature*/feature.patch")):
        for line in patch.read_bytes().split(b"\n"):
            if line.startswith(b"diff --git"):
                if line.endswith(b"\r"):
                    raise CooperBenchImportError(
                        f"{patch}: patch lines end in CRLF, so the checkout was rewritten "
                        "by core.autocrlf; re-clone with `git -c core.autocrlf=false clone`"
                    )
                return


def parse_base_spec(task_dir: Path) -> BaseSpec:
    """Read a task's repository URL and base commit out of its own files.

    The `Dockerfile` states both in one place (`git clone <url> repo && ...
    git checkout <sha>`); `setup.sh` states them again, sometimes through
    shell variables. Neither file is executed: they are read as text.
    """
    task_dir = Path(task_dir)
    dockerfile = task_dir / "Dockerfile"
    if dockerfile.is_file():
        text = dockerfile.read_text(encoding="utf-8", errors="replace")
        clone = re.search(r"git clone\s+(\S+)", text)
        checkout = re.search(r"git checkout\s+([0-9a-f]{40})", text)
        if clone and checkout:
            return BaseSpec(_normalize_url(clone.group(1)), checkout.group(1))

    setup = task_dir / "setup.sh"
    if setup.is_file():
        text = setup.read_text(encoding="utf-8", errors="replace")
        variables = dict(re.findall(r'^([A-Z_]+)="([^"]*)"', text, flags=re.MULTILINE))
        commit = variables.get("BASE_COMMIT")
        clone = re.search(r"git clone\s+(\S+)", text)
        if commit and _SHA.fullmatch(commit) and clone:
            url = clone.group(1).strip('"')
            for name, value in variables.items():
                url = url.replace("${" + name + "}", value).replace("$" + name, value)
            if "$" not in url:
                return BaseSpec(_normalize_url(url), commit)

    raise BaseResolutionError(f"{task_dir.name}: no repository URL and base commit found")


def _normalize_url(url: str) -> str:
    url = url.strip().strip('"')
    return url[:-4] if url.endswith(".git") else url


# ---------------------------------------------------------------------------
# Base-repo resolution
# ---------------------------------------------------------------------------


class GitBaseResolver:
    """Fetches one commit, shallow and blob-less, and reads named files from it.

    One repository directory per upstream URL under `cache_dir/repos/`; a
    second task at another commit of the same repository reuses it. Nothing
    is checked out: files are read from the object database with
    `git cat-file --batch`, which fetches only the blobs it is asked for.
    """

    def __init__(self, cache_dir: Path, *, timeout: int = 900) -> None:
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout

    def _repo_dir(self, url: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1]).strip("_")
        return self.cache_dir / "repos" / slug

    def _git(self, repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
        env = _git_env()
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=repo,
                input=input_bytes,
                capture_output=True,
                timeout=self.timeout,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BaseResolutionError(f"git {args[0]}: {type(exc).__name__}: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise BaseResolutionError(f"git {args[0]} failed: {detail[:300]}")
        return completed.stdout

    def ensure_commit(self, spec: BaseSpec) -> Path:
        repo = self._repo_dir(spec.repo_url)
        if not (repo / ".git").exists():
            repo.mkdir(parents=True, exist_ok=True)
            self._git(repo, "init", "-q")
            self._git(repo, "remote", "add", "origin", spec.repo_url)
            self._git(repo, "config", "extensions.partialClone", "origin")
            self._git(repo, "config", "remote.origin.promisor", "true")
            self._git(repo, "config", "remote.origin.partialclonefilter", "blob:none")
        try:
            self._git(repo, "cat-file", "-e", f"{spec.commit}^{{commit}}")
            return repo
        except BaseResolutionError:
            pass
        self._git(
            repo, "fetch", "--depth", "1", "--filter=blob:none", "--no-tags", "origin", spec.commit
        )
        return repo

    def read_files(self, spec: BaseSpec, paths: Iterable[str]) -> dict[str, BaseFile]:
        wanted = sorted(set(paths))
        if not wanted:
            return {}
        repo = self.ensure_commit(spec)
        request = "".join(f"{spec.commit}:{path}\n" for path in wanted).encode("utf-8")
        raw = self._git(repo, "cat-file", "--batch", input_bytes=request)
        result: dict[str, BaseFile] = {}
        cursor = 0
        for path in wanted:
            end = raw.find(b"\n", cursor)
            if end < 0:
                raise BaseResolutionError("git cat-file --batch: truncated output")
            header = raw[cursor:end].decode("utf-8", errors="replace")
            cursor = end + 1
            if header.endswith(" missing"):
                result[path] = None
                continue
            parts = header.split()
            if len(parts) != 3:
                raise BaseResolutionError(f"git cat-file --batch: unexpected header {header!r}")
            size = int(parts[2])
            body = raw[cursor : cursor + size]
            cursor += size + 1
            if parts[1] != "blob":
                result[path] = None
                continue
            try:
                if b"\x00" in body:
                    raise UnicodeDecodeError("utf-8", b"", 0, 1, "NUL byte")
                result[path] = body.decode("utf-8")
            except UnicodeDecodeError:
                result[path] = BINARY
        return result


def _git_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    return env


# ---------------------------------------------------------------------------
# The offline oracle
# ---------------------------------------------------------------------------


def line_digest(text: str) -> str:
    """Order-insensitive digest of a file's normalized lines."""
    lines = sorted(
        stripped
        for stripped in (raw.replace("\r", "").rstrip() for raw in text.split("\n"))
        if stripped
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _line_counts(text: str) -> Counter[str]:
    return Counter(
        stripped
        for stripped in (raw.replace("\r", "").rstrip() for raw in text.split("\n"))
        if stripped
    )


def _digest_of_counts(counts: Counter[str]) -> str:
    lines = sorted(line for line, count in counts.items() for _ in range(count))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def expected_digests(
    base_files: dict[str, str],
    writes_a: dict[str, str],
    writes_b: dict[str, str],
    touched_a: Iterable[str],
    touched_b: Iterable[str],
) -> tuple[dict[str, str], list[str]]:
    """Digest of the merged file expected at each touched path.

    Expected line counts are `base + (A - base) + (B - base)`, floored at
    zero. A path a patch touches but the importer wrote nothing for (the
    patch deleted it) is returned in the skipped list, not checked.
    """
    touched_a = set(touched_a)
    touched_b = set(touched_b)
    expected: dict[str, str] = {}
    skipped: list[str] = []
    for path in sorted(touched_a | touched_b):
        if (path in touched_a and path not in writes_a) or (
            path in touched_b and path not in writes_b
        ):
            skipped.append(path)
            continue
        base = _line_counts(base_files.get(path, ""))
        after_a = _line_counts(writes_a[path]) if path in touched_a else base
        after_b = _line_counts(writes_b[path]) if path in touched_b else base
        merged: Counter[str] = Counter()
        for line in set(base) | set(after_a) | set(after_b):
            value = base[line] + (after_a[line] - base[line]) + (after_b[line] - base[line])
            if value > 0:
                merged[line] = value
        expected[path] = _digest_of_counts(merged)
    return expected, skipped


_VERIFIER_TEMPLATE = '''\
"""Offline oracle for an imported CooperBench pair (see causalmesh.tasks.cooperbench_batch).

Checks that every path listed in cb_expected.json holds exactly the expected
multiset of normalized lines. Stdlib only; executes nothing from the target
repository. This is NOT the CooperBench hidden test suite.
"""
import hashlib
import json
import sys


{digest_source}


def main():
    with open("cb_expected.json", encoding="utf-8") as handle:
        expected = json.load(handle)["paths"]
    failures = []
    for path, digest in sorted(expected.items()):
        try:
            with open(path, "rb") as handle:
                text = handle.read().decode("utf-8", errors="replace")
        except OSError:
            failures.append(path + " (missing)")
            continue
        if line_digest(text) != digest:
            failures.append(path + " (content differs from the merged expectation)")
    if failures:
        print("ORACLE FAIL: %d of %d path(s)" % (len(failures), len(expected)))
        for failure in failures:
            print("  " + failure)
        return 1
    print("ORACLE OK: %d path(s)" % len(expected))
    return 0


sys.exit(main())
'''


def verifier_source() -> str:
    """The stdlib-only verifier, sharing `line_digest`'s source with the importer."""
    return _VERIFIER_TEMPLATE.format(digest_source=inspect.getsource(line_digest).rstrip())


RUN_TESTS_SH = """\
#!/usr/bin/env bash
# Offline oracle written by the CooperBench batch importer. It replaces the
# dataset's own run_tests.sh, which needs a network and a per-repo toolchain.
set -euo pipefail
python cb_verify.py
"""


# ---------------------------------------------------------------------------
# One pair
# ---------------------------------------------------------------------------


def _write_actions(imported: ImportedTask, agent: str) -> dict[str, str]:
    actions = imported.definition.scenario[agent]["actions"]
    return {item["write"]["path"]: item["write"]["content"] for item in actions if "write" in item}


def _sequential_apply_check(
    base_files: dict[str, str],
    writes_a: dict[str, str],
    patch_b: str,
    expected: dict[str, str],
) -> str:
    """Cross-check the oracle against a real `git apply` of B on top of A.

    When feature B's patch applies on the tree left by feature A's, that
    tree is a merge produced by git itself. The oracle's digests must equal
    it, or the multiset formula is wrong for this pair. Returns `matches`,
    `differs`, or `not_applicable` (B does not apply on A: the pair's gold
    patches conflict, so there is no independent merge to compare with).
    """
    from .cooperbench import _apply_patch

    after_a = dict(base_files)
    after_a.update(writes_a)
    try:
        merged = _apply_patch(after_a, patch_b, source=Path("feature2"))
    except CooperBenchImportError:
        return "not_applicable"
    for path, digest in expected.items():
        if line_digest(merged.get(path, "")) != digest:
            return "differs"
    return "matches"


def _stage_pair(dataset: Path, key: PairKey, stage_root: Path) -> Path:
    """Copy the two features into the `feature1/`, `feature2/` shape `import_task` reads."""
    task_dir = dataset / key.repo / key.task
    stage = stage_root / key.repo / f"{key.task}_f{key.first}_f{key.second}"
    if stage.exists():
        shutil.rmtree(stage)
    for slot, number in (("feature1", key.first), ("feature2", key.second)):
        source = task_dir / f"feature{number}"
        target = stage / slot
        target.mkdir(parents=True)
        for name in ("feature.md", "feature.patch"):
            if (source / name).is_file():
                shutil.copyfile(source / name, target / name)
    return stage


def feature_touched_paths(dataset: Path, key: PairKey) -> set[str]:
    """Paths the pair's two `feature.patch` files touch (for base-file prefetch)."""
    from .cooperbench import touched_paths

    paths: set[str] = set()
    for number in (key.first, key.second):
        patch = dataset / key.repo / key.task / f"feature{number}" / "feature.patch"
        paths |= touched_paths(patch.read_bytes().decode("utf-8", errors="replace"))
    return paths


def _record(
    key: PairKey, status: str, stage: str, reason: str | None, **extra: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "features": [key.first, key.second],
        "pair_id": key.pair_id,
        "reason": reason,
        "repo": key.repo,
        "stage": stage,
        "status": status,
        "task": key.task,
        "task_id": key.task_id,
    }
    record.update(extra)
    return record


def process_pair(
    key: PairKey,
    *,
    dataset: Path,
    output_dir: Path,
    base_files_by_path: dict[str, BaseFile],
    base: BaseSpec | None,
    seed: bytes = DEFAULT_SEED,
    repetitions: int = 1,
    keep_workspaces: bool = False,
) -> dict[str, Any]:
    """Import one pair, validate it, and run the real section-37 gate on it.

    Never raises: any exception becomes a `failed` record naming the stage.
    """
    stage_name = "import"
    base_dict = base.to_dict() if base else None
    scratch = output_dir / "work" / key.task_id
    try:
        touched = feature_touched_paths(dataset, key)
        binary = sorted(p for p in touched if isinstance(base_files_by_path.get(p), _Binary))
        if binary:
            return _record(
                key,
                "skipped",
                "import",
                f"binary_base_file: {binary[0]}"
                + (f" (+{len(binary) - 1} more)" if len(binary) > 1 else ""),
                base=base_dict,
            )
        pair_base = {
            path: value
            for path, value in base_files_by_path.items()
            if path in touched and isinstance(value, str)
        }

        stage_dir = _stage_pair(dataset, key, scratch / "stage")
        imported = import_task(
            stage_dir,
            base_files=pair_base,
            options=ImportOptions(task_id=key.task_id),
        )

        writes_a = _write_actions(imported, "agent_a")
        writes_b = _write_actions(imported, "agent_b")
        expected, deleted = expected_digests(
            pair_base,
            writes_a,
            writes_b,
            imported.features["agent_a"].touched,
            imported.features["agent_b"].touched,
        )
        common = {
            "base": base_dict,
            "contested_paths": sorted(imported.definition.contested_paths),
            "oracle": {
                "paths_checked": len(expected),
                "paths_skipped_deleted": len(deleted),
                "sequential_apply": _sequential_apply_check(
                    pair_base, writes_a, imported.features["agent_b"].patch_text, expected
                ),
            },
            "touched": {
                "agent_a": len(imported.features["agent_a"].touched),
                "agent_b": len(imported.features["agent_b"].touched),
            },
        }

        imported.setup_sh = None
        imported.run_tests_sh = RUN_TESTS_SH
        fixtures_root = output_dir / "fixtures"
        imported.write_fixture(fixtures_root / imported.definition.fixture)
        fixture = fixtures_root / imported.definition.fixture
        (fixture / "cb_verify.py").write_bytes(verifier_source().encode("utf-8"))
        (fixture / "cb_expected.json").write_text(
            json.dumps({"paths": expected, "version": 1}, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        yaml_path = imported.write_yaml(
            output_dir / "tasks" / f"{imported.definition.task_id}.yaml"
        )
        reloaded = TaskDefinition.from_yaml(yaml_path)
        if reloaded.content_hash() != imported.definition.content_hash():
            return _record(key, "failed", "import", "yaml_round_trip_mismatch", **common)

        stage_name = "structure"
        report = validate_structure(imported.definition, fixtures_root=fixtures_root)
        structure = {
            "errors": sorted({issue.code for issue in report.errors}),
            "valid": report.valid,
            "warnings": sorted({issue.code for issue in report.warnings}),
        }
        if not report.valid:
            codes = structure["errors"]
            if codes == ["no_coordination_dependency"]:
                return _record(
                    key,
                    "skipped",
                    "structure",
                    "no_coordination_dependency: the two features touch disjoint paths",
                    structure=structure,
                    **common,
                )
            return _record(
                key,
                "failed",
                "structure",
                "structure_invalid: " + ",".join(codes),
                structure=structure,
                **common,
            )

        stage_name = "sensitivity"
        verdict = asyncio.run(
            check_sensitivity(
                imported.definition,
                workspace_root=scratch / "gate",
                fixtures_root=fixtures_root,
                master_seed=seed,
                repetitions=repetitions,
            )
        )
        return _record(
            key,
            "sensitive" if verdict.sensitive else "not_sensitive",
            "done",
            None,
            sensitivity=verdict.to_dict(),
            structure=structure,
            **common,
        )
    except BaseException as exc:  # noqa: BLE001 - one pair must never abort the batch
        if isinstance(exc, KeyboardInterrupt):
            raise
        message = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:400]
        code = (
            "patch_does_not_apply"
            if isinstance(exc, CooperBenchImportError) and "did not apply" in str(exc)
            else "exception"
        )
        return _record(key, "failed", stage_name, f"{code}: {message}", base=base_dict)
    finally:
        if not keep_workspaces:
            shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# The batch
# ---------------------------------------------------------------------------


def load_results(path: Path) -> dict[str, dict[str, Any]]:
    """Latest record per pair from a results JSONL; unreadable lines are ignored."""
    latest: dict[str, dict[str, Any]] = {}
    path = Path(path)
    if not path.is_file():
        return latest
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and "pair_id" in record:
            latest[record["pair_id"]] = record
    return latest


def _dataset_provenance(dataset_dir: Path) -> dict[str, str]:
    root = dataset_dir.parent if dataset_dir.name == "dataset" else dataset_dir
    commit = NULL_STATUS
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode == 0 and _SHA.fullmatch(completed.stdout.strip()):
            commit = completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    licence = NULL_STATUS
    readme = dataset_dir / "README.md"
    if readme.is_file():
        match = re.search(
            r"^license:\s*(\S+)\s*$",
            readme.read_text(encoding="utf-8", errors="replace"),
            flags=re.MULTILINE,
        )
        if match:
            licence = match.group(1)
    return {"dataset_commit": commit, "dataset_license_declared": licence}


def summarize(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Counts and reasons over a set of pair records."""
    statuses = Counter(record["status"] for record in results.values())
    reasons: Counter[str] = Counter()
    per_task: dict[str, Counter[str]] = {}
    for record in results.values():
        per_task.setdefault(f"{record['repo']}/{record['task']}", Counter())[record["status"]] += 1
        if record["status"] in ("skipped", "failed"):
            reason = str(record.get("reason") or NULL_STATUS)
            reasons[f"{record['status']}: {reason.split(':', 1)[0]}"] += 1
    gated = statuses["sensitive"] + statuses["not_sensitive"]
    return {
        "pairs_total": len(results),
        "status": dict(sorted(statuses.items())),
        "gated": gated,
        "sensitive": statuses["sensitive"],
        "not_sensitive": statuses["not_sensitive"],
        "skipped": statuses["skipped"],
        "failed": statuses["failed"],
        "reasons": dict(sorted(reasons.items())),
        "pairs_with_contested_paths": sum(
            1 for record in results.values() if record.get("contested_paths")
        ),
        "gated_with_informed_success": sum(
            1
            for record in results.values()
            if record.get("sensitivity", {}).get("informed_successes", 0) > 0
        ),
        "oracle_sequential_apply": dict(
            sorted(
                Counter(
                    str(record.get("oracle", {}).get("sequential_apply", NULL_STATUS))
                    for record in results.values()
                    if "oracle" in record
                ).items()
            )
        ),
        "per_task": {task: dict(sorted(c.items())) for task, c in sorted(per_task.items())},
    }


def _process_pair_job(payload: dict[str, Any]) -> dict[str, Any]:
    """Top-level wrapper so a process pool can pickle the call."""
    return process_pair(**payload)


def run_batch(
    options: BatchOptions,
    *,
    resolver: BaseResolver,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Import and gate every selected pair; return the summary document."""
    started = time.time()
    say = progress or (lambda _message: None)
    dataset = resolve_dataset_dir(options.dataset_dir)
    output_dir = Path(options.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl = output_dir / "results.jsonl"

    check_checkout_line_endings(dataset)
    pairs = discover_pairs(options)
    existing = load_results(jsonl)
    todo = [
        key
        for key in pairs
        if options.force or existing.get(key.pair_id, {}).get("status") not in TERMINAL_STATUSES
    ]
    say(f"pairs selected: {len(pairs)}; to process: {len(todo)}; resumed: {len(pairs) - len(todo)}")

    by_task: dict[str, list[PairKey]] = {}
    for key in todo:
        by_task.setdefault(key.task_dir_name, []).append(key)

    def append(record: dict[str, Any]) -> None:
        with jsonl.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        existing[record["pair_id"]] = record
        say(
            f"{record['pair_id']}: {record['status']}"
            + (f" ({record['reason']})" if record["reason"] else "")
        )

    with ExitStack() as stack:
        pool = None
        if options.jobs > 1:
            from concurrent.futures import ProcessPoolExecutor

            # One pool for the whole batch: each worker pays the package import once.
            pool = stack.enter_context(ProcessPoolExecutor(max_workers=options.jobs))
        for task_name, keys in sorted(by_task.items()):
            task_dir = dataset / task_name
            base: BaseSpec | None = None
            base_files: dict[str, BaseFile] = {}
            try:
                base = parse_base_spec(task_dir)
                needed: set[str] = set()
                for key in keys:
                    needed |= feature_touched_paths(dataset, key)
                base_files = resolver.read_files(base, needed)
            except Exception as exc:  # noqa: BLE001 - a task with no base fails its own pairs only
                reason = f"base_unavailable: {type(exc).__name__}: {exc}".replace("\n", " ")[:400]
                for key in keys:
                    append(
                        _record(
                            key, "failed", "base", reason, base=base.to_dict() if base else None
                        )
                    )
                continue

            payloads = [
                {
                    "key": key,
                    "dataset": dataset,
                    "output_dir": output_dir,
                    "base_files_by_path": base_files,
                    "base": base,
                    "seed": options.seed,
                    "repetitions": options.repetitions,
                    "keep_workspaces": options.keep_workspaces,
                }
                for key in keys
            ]
            if pool is not None:
                for record in pool.map(_process_pair_job, payloads):
                    append(record)
            else:
                for payload in payloads:
                    append(process_pair(**payload))

    selected = {key.pair_id for key in pairs}
    final = {pair_id: record for pair_id, record in existing.items() if pair_id in selected}
    document = {
        "envelope": {
            "elapsed_seconds": round(time.time() - started, 1),
            "finished_unix": int(time.time()),
            "note": (
                "Every run is a deterministic scripted mock agent; the success test is an "
                "offline line-multiset oracle, not the CooperBench hidden tests; the "
                "contested-path merge is winner-take-all. These verdicts say nothing about "
                "real agent coordination."
            ),
            "python": sys.version.split()[0],
            **_dataset_provenance(dataset),
        },
        "options": {
            "repetitions": options.repetitions,
            "seed": options.seed.decode("utf-8", errors="replace"),
        },
        "summary": summarize(final),
        "pairs": [final[key.pair_id] for key in pairs if key.pair_id in final],
    }
    (output_dir / "results.json").write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return document
