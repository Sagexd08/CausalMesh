"""Supplying a CooperBench task's pre-patch base repository (backlog §54).

**How the real dataset supplies the base repo: it does not vendor it.** Each
`dataset/<repo>/task<id>/` directory carries `setup.sh` and a `Dockerfile`,
and both name the same two facts: an upstream clone URL and a pinned
`BASE_COMMIT`. The repository state a task's patches apply to is therefore
"that upstream repository at that commit", fetched from the network, never a
file in the CooperBench checkout. (The `Dockerfile` bakes the same clone
into a published image, `akhatua/cooperbench-<repo>:task<id>`; this module
does not use the images, which are large and need a container runtime.)

This module turns those two facts back into files, in two sizes:

- `base_files_for_paths` fetches **only the files a set of patches touches**,
  using a blobless shallow fetch of the one pinned commit
  (`git fetch --depth 1 --filter=blob:none origin <sha>`, then one object
  read per path). That is kilobytes to a few megabytes per task even for
  large upstream repositories, and it is all `import_task` needs: a
  feature patch only ever reads the files it edits.
- `checkout_base_repo` materializes the **whole tree** of the pinned commit
  into a directory, for the cases that genuinely need to run the
  repository's own tests (the §37 gate).

Both shell out to `git`, the same tool `cooperbench._apply_patch` already
depends on, and neither executes anything from the dataset: `setup.sh` is
only *read*, for two assignments and one clone URL, never run. That matters
for the reason `import_task`'s own docstring gives: running an unknown shell
script from imported data at import time is the "arbitrary code" risk the
task system is built to avoid.

Network is needed the first time a commit is fetched. A `cache_dir` makes a
second read of the same commit offline.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "BaseRepoError",
    "BaseSpec",
    "base_files_for_paths",
    "checkout_base_repo",
    "parse_base_spec",
]


class BaseRepoError(ValueError):
    """The base repository for a task could not be determined or fetched.

    A `ValueError` like `CooperBenchImportError`, and deliberately not a
    subclass of it: `cooperbench` imports this module, so the dependency
    only points one way. `cooperbench` wraps it where a caller needs one
    exception type.
    """


@dataclass(frozen=True)
class BaseSpec:
    """The two facts that name a task's base repository."""

    repo_url: str
    base_commit: str


_ASSIGNMENT = re.compile(r"""^\s*([A-Za-z_][A-Za-z0-9_]*)=["']?([^"'\s#]*)["']?""")
_CLONE = re.compile(r"""\bgit\s+clone\s+(?:--\S+\s+)*["']?(\S+?)["']?(?:\s|$)""")
_VARIABLE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def parse_base_spec(setup_sh: str) -> BaseSpec:
    """Read the clone URL and `BASE_COMMIT` out of a CooperBench `setup.sh`.

    Pure text parsing; nothing is executed. Handles the two shapes present
    in the real dataset: a literal URL (`git clone https://github.com/x/y`),
    and a URL built from earlier assignments
    (`git clone https://github.com/${REPO_OWNER}/${REPO_NAME}`, used by the
    typst task). An unresolved variable is an error, not a guess.
    """
    variables: dict[str, str] = {}
    for line in setup_sh.splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            variables.setdefault(match.group(1), match.group(2))

    commit = variables.get("BASE_COMMIT")
    if commit is None or not _SHA.match(commit):
        raise BaseRepoError(f"setup.sh does not pin a 40-hex BASE_COMMIT (found {commit!r})")

    clone = None
    for line in setup_sh.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _CLONE.search(line)
        if match:
            clone = match.group(1)
            break
    if clone is None:
        raise BaseRepoError("setup.sh has no `git clone` line naming the upstream repository")

    unresolved: list[str] = []

    def _substitute(found: re.Match[str]) -> str:
        name = found.group(1) or found.group(2)
        if name in variables:
            return variables[name]
        unresolved.append(name)
        return found.group(0)

    url = _VARIABLE.sub(_substitute, clone)
    if unresolved:
        raise BaseRepoError(f"clone URL {clone!r} uses unresolved variables {sorted(unresolved)}")
    if not url.startswith(("https://", "http://", "git://", "file://", "/")):
        raise BaseRepoError(f"clone URL {url!r} is not a recognizable remote")
    return BaseSpec(repo_url=url, base_commit=commit)


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(
    args: list[str], *, cwd: Path, timeout: int = 600, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    # core.longpaths: a promisor fetch of a deeply nested cache repo otherwise
    # fails on Windows with "Filename too long" (MAX_PATH), and a lazy blob
    # fetch inside `cat-file` fails the same way and reads as "missing".
    try:
        return subprocess.run(
            ["git", "-c", "core.longpaths=true", *args],
            cwd=cwd,
            input=stdin,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BaseRepoError(f"git {' '.join(args[:2])} could not run: {exc}") from exc


def _cache_name(url: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", url).strip("_")


def _ensure_commit(spec: BaseSpec, repo: Path, *, blobless: bool) -> None:
    """Make `spec.base_commit` present in the (possibly shared) repo at `repo`."""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists() and not (repo / "HEAD").exists():
        init = _git(["init", "-q", "."], cwd=repo)
        if init.returncode != 0:
            raise BaseRepoError(f"git init failed: {init.stderr.decode(errors='replace').strip()}")
    present = _git(["cat-file", "-e", f"{spec.base_commit}^{{commit}}"], cwd=repo)
    if present.returncode == 0:
        return
    _git(["remote", "remove", "origin"], cwd=repo)
    added = _git(["remote", "add", "origin", spec.repo_url], cwd=repo)
    if added.returncode != 0:
        raise BaseRepoError(f"git remote add failed: {added.stderr.decode(errors='replace')}")
    fetch_args = ["fetch", "-q", "--depth", "1"]
    if blobless:
        fetch_args.append("--filter=blob:none")
    fetch_args += ["origin", spec.base_commit]
    fetched = _git(fetch_args, cwd=repo)
    if fetched.returncode != 0:
        raise BaseRepoError(
            f"could not fetch {spec.base_commit[:12]} from {spec.repo_url}: "
            f"{fetched.stderr.decode(errors='replace').strip()[:300]}"
        )


def base_files_for_paths(
    spec: BaseSpec, paths: set[str] | frozenset[str], *, cache_dir: Path
) -> dict[str, str]:
    """Return `{path: text}` for each of `paths` that exists at the base commit.

    A path absent from the commit is simply absent from the result: a
    feature patch that *creates* a file names a path the base does not have,
    and that is correct, not an error. Whether a patch that *edits* a file
    finds it is decided later, by applying the patch.

    Content is decoded as strict UTF-8 and returned byte-for-byte (line
    endings included). A non-UTF-8 file raises `BaseRepoError` rather than
    being decoded lossily: a lossy base would make the materialized write
    actions differ from what the patch really produces.
    """
    cache_dir = Path(cache_dir)
    repo = cache_dir / _cache_name(spec.repo_url)
    _ensure_commit(spec, repo, blobless=True)

    wanted = sorted(paths)
    if not wanted:
        return {}
    request = "".join(f"{spec.base_commit}:{path}\n" for path in wanted).encode("utf-8")
    completed = _git(["cat-file", "--batch"], cwd=repo, timeout=900, stdin=request)
    if completed.returncode != 0:
        raise BaseRepoError(
            f"git cat-file failed: {completed.stderr.decode(errors='replace').strip()[:300]}"
        )

    out = completed.stdout
    cursor = 0
    files: dict[str, str] = {}
    for path in wanted:
        end = out.index(b"\n", cursor)
        header = out[cursor:end].decode("utf-8", errors="replace").split()
        cursor = end + 1
        if header[-1] == "missing":
            continue
        if len(header) != 3:
            raise BaseRepoError(f"unexpected cat-file header for {path!r}: {header!r}")
        _, kind, size_text = header
        size = int(size_text)
        body = out[cursor : cursor + size]
        cursor += size + 1
        if kind != "blob":
            continue
        try:
            files[path] = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise BaseRepoError(f"{path}: not valid UTF-8 at the base commit ({exc})") from exc
    return files


def checkout_base_repo(spec: BaseSpec, destination: Path, *, cache_dir: Path) -> Path:
    """Write the whole tree of `spec.base_commit` into `destination`.

    Uses a full (not blobless) shallow fetch into its own cache entry, then
    `git archive`-style export through `checkout-index`, so `destination`
    holds plain files with no `.git` directory. Sized by the upstream
    repository at that commit: use it only for repositories you intend to
    run.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    repo = Path(cache_dir) / f"{_cache_name(spec.repo_url)}_full"
    _ensure_commit(spec, repo, blobless=False)
    reset = _git(["read-tree", spec.base_commit], cwd=repo)
    if reset.returncode != 0:
        raise BaseRepoError(f"git read-tree failed: {reset.stderr.decode(errors='replace')}")
    prefix = str(destination.resolve()) + os.sep
    exported = _git(["checkout-index", "-a", "-f", f"--prefix={prefix}"], cwd=repo)
    if exported.returncode != 0:
        raise BaseRepoError(
            f"git checkout-index failed: {exported.stderr.decode(errors='replace').strip()}"
        )
    return destination
