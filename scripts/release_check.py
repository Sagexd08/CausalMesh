"""Every check that can be made before a release is uploaded, and no upload.

    python scripts/release_check.py             # check the tree and the files in dist/
    python scripts/release_check.py --build     # rebuild dist/ first (sdist + wheel)
    python scripts/release_check.py --gate      # also run scripts/check.py (10-15 minutes)
    python scripts/release_check.py --smoke     # also install the wheel in a fresh venv

There is no CI (AGENTS.md), so a release is a person at a terminal, and this
script is the list that person would otherwise keep in their head. It reports
READY only when everything it checks held and the gate ran and passed.

**It refuses to upload, on purpose.** Uploading to PyPI cannot be undone (a
filename is used once, even after a release is yanked or deleted), so the
upload is a separate, typed, deliberate command in docs/RELEASING.md. This file
contains no upload code, and `--upload` (or anything like it) is an error.

What it checks:

1. the working tree is clean, HEAD is on a branch, and the tag `vX.Y.Z` is free;
2. one version: `causalmesh.__version__` is the only place it is written, is a
   valid PEP 440 version, and CHANGELOG.md has a `## [X.Y.Z]` section for it;
3. the gate: `scripts/check.py` passes (only with --gate; otherwise the report
   says the gate was NOT run and the verdict cannot be READY);
4. dist/ holds exactly one sdist and one wheel for that version; the wheel is
   pure-Python `py3-none-any`, carries the licence and the typing marker, and
   contains no tests, fixtures, run data, keys or environment files; the sdist
   carries no fixtures, data, videos or website;
5. `twine check --strict` passes on both files.

Output is ASCII (Windows consoles default to cp1252). Exit 0 means READY, 1
means something failed or the gate was skipped, 2 means it was misused.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "causalmesh"

# Paths that must never be inside a distribution. Matched against path parts.
WHEEL_FORBIDDEN_TOP = {"tests", "fixtures", "data", "videos", "frontend", "docs", "scripts"}
SDIST_FORBIDDEN_TOP = {"fixtures", "data", "videos", "frontend", "artifacts", "experiments"}
SECRET_SUFFIXES = (".key", ".pem", ".env", ".pyc")

VERSION_RE = re.compile(r"^(\d+)(\.\d+)*((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?$")
UPLOAD_WORDS = ("upload", "publish", "twine-upload", "push")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []  # (status, label)

    def add(self, ok: bool, label: str, detail: str = "") -> bool:
        self.rows.append(("PASS" if ok else "FAIL", label))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        if not ok and detail:
            for line in detail.strip().splitlines()[-10:]:
                print("         " + line.encode("ascii", "replace").decode("ascii"))
        return ok

    def note(self, label: str) -> None:
        self.rows.append(("NOTE", label))
        print(f"  [NOTE] {label}")

    def not_run(self, label: str) -> None:
        self.rows.append(("SKIP", label))
        print(f"  [SKIP] {label}")

    @property
    def failed(self) -> list[str]:
        return [label for status, label in self.rows if status == "FAIL"]

    @property
    def skipped(self) -> list[str]:
        return [label for status, label in self.rows if status == "SKIP"]


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------


def read_version(root: Path = ROOT) -> str | None:
    """`__version__` from the package source, read without importing it."""
    tree = ast.parse((root / "src" / PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets
        ):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    return None


def changelog_sections(text: str) -> dict[str, str]:
    """Map each `## [heading]` in a changelog to the text under it.

    A section ends at the next `## ` heading of any kind, so the closing
    "Before this file existed" note is not counted as part of the last release.
    """
    headings = list(re.finditer(r"^## (.*)$", text, flags=re.MULTILINE))
    sections: dict[str, str] = {}
    for i, match in enumerate(headings):
        named = re.match(r"\[([^\]]+)\]", match.group(1))
        if named:
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            sections[named.group(1)] = text[match.end() : end].strip()
    return sections


def check_version(report: Report, root: Path = ROOT) -> str | None:
    version = read_version(root)
    if not report.add(version is not None, "__version__ is a string literal in the package"):
        return None
    assert version is not None
    report.add(bool(VERSION_RE.match(version)), f"{version} is a valid PEP 440 version")

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    static = re.search(r"^version\s*=", pyproject, flags=re.MULTILINE)
    report.add(
        static is None and 'dynamic = ["version"]' in pyproject,
        "pyproject.toml takes its version from the package (written once)",
    )

    sections = changelog_sections((root / "CHANGELOG.md").read_text(encoding="utf-8"))
    report.add(
        version in sections and bool(sections[version]),
        f"CHANGELOG.md has a non-empty '## [{version}]' section",
        "move the Unreleased entries under a dated heading (docs/RELEASING.md step 1)",
    )
    if sections.get("Unreleased"):
        report.note("CHANGELOG.md [Unreleased] still has entries; after the cut it should be empty")
    return version


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def git(*args: str, root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8"
    )


def check_git(report: Report, version: str | None, root: Path = ROOT) -> None:
    status = git("status", "--porcelain", root=root)
    report.add(
        status.returncode == 0 and status.stdout.strip() == "",
        "working tree is clean (nothing uncommitted, nothing untracked)",
        status.stdout + status.stderr,
    )
    branch = git("symbolic-ref", "--short", "-q", "HEAD", root=root)
    name = branch.stdout.strip()
    report.add(bool(name), f"HEAD is on a branch ({name or 'detached'})")
    if name and name != "main":
        report.note(f"releasing from '{name}', not 'main'; RELEASING.md tags the merge on main")
    if version:
        tag = git("rev-parse", "-q", "--verify", f"refs/tags/v{version}", root=root)
        report.add(tag.returncode != 0, f"tag v{version} does not exist yet")


# ---------------------------------------------------------------------------
# Gate, build, smoke, twine
# ---------------------------------------------------------------------------


def run_step(argv: list[str], *, root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        argv, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def check_gate(report: Report, *, run_gate: bool) -> None:
    if not run_gate:
        report.not_run("gate: scripts/check.py was NOT run (pass --gate; a release needs it)")
        return
    print("  running scripts/check.py; this takes 10-15 minutes ...", flush=True)
    done = run_step([sys.executable, "scripts/check.py"])
    tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-8:])
    report.add(done.returncode == 0, "gate: python scripts/check.py passes", tail)


def build(report: Report, dist: Path) -> None:
    for old in dist.glob(f"{PACKAGE}-*"):
        old.unlink()
    done = run_step([sys.executable, "-m", "build", "--outdir", str(dist)])
    report.add(
        done.returncode == 0,
        "python -m build (sdist, then the wheel from the sdist)",
        done.stdout + done.stderr,
    )


def artifacts(dist: Path, version: str) -> tuple[Path | None, Path | None, list[Path]]:
    files = sorted(p for p in dist.glob("*") if p.is_file())
    wheels = [p for p in files if p.suffix == ".whl"]
    sdists = [p for p in files if p.name.endswith(".tar.gz")]
    other = [p for p in files if p not in wheels and p not in sdists]
    wheel = wheels[0] if len(wheels) == 1 else None
    sdist = sdists[0] if len(sdists) == 1 else None
    problems = other + (wheels if len(wheels) != 1 else []) + (sdists if len(sdists) != 1 else [])
    return wheel, sdist, problems


def wheel_problems(path: Path, version: str) -> list[str]:
    problems: list[str] = []
    if not path.name.endswith("-py3-none-any.whl"):
        problems.append(f"{path.name} is not a pure-Python py3-none-any wheel")
    if not path.name.startswith(f"{PACKAGE}-{version}-"):
        problems.append(f"{path.name} does not carry version {version}")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        wheel_meta = z.read(f"{PACKAGE}-{version}.dist-info/WHEEL").decode("utf-8", "replace")
    if "Root-Is-Purelib: true" not in wheel_meta:
        problems.append("WHEEL says Root-Is-Purelib is not true")
    for required in (
        f"{PACKAGE}/__init__.py",
        f"{PACKAGE}/__main__.py",
        f"{PACKAGE}/py.typed",
        f"{PACKAGE}/cli/main.py",
        f"{PACKAGE}-{version}.dist-info/licenses/LICENSE",
        f"{PACKAGE}-{version}.dist-info/entry_points.txt",
    ):
        if required not in names:
            problems.append(f"missing from the wheel: {required}")
    for name in names:
        top = name.split("/")[0]
        if top != PACKAGE and not top.endswith(".dist-info"):
            problems.append(f"unexpected top-level entry in the wheel: {name}")
        if top in WHEEL_FORBIDDEN_TOP or name.endswith(SECRET_SUFFIXES) or "/.env" in name:
            problems.append(f"does not belong in the wheel: {name}")
    return problems


def sdist_problems(path: Path, version: str) -> list[str]:
    problems: list[str] = []
    prefix = f"{PACKAGE}-{version}"
    with tarfile.open(path) as t:
        names = t.getnames()
    if not path.name.startswith(prefix):
        problems.append(f"{path.name} does not carry version {version}")
    for required in (
        f"{prefix}/pyproject.toml",
        f"{prefix}/README.md",
        f"{prefix}/LICENSE",
        f"{prefix}/src/{PACKAGE}/__init__.py",
        f"{prefix}/src/{PACKAGE}/py.typed",
    ):
        if required not in names:
            problems.append(f"missing from the sdist: {required}")
    for name in names:
        parts = name.split("/")
        if len(parts) > 1 and parts[1] in SDIST_FORBIDDEN_TOP:
            problems.append(f"does not belong in the sdist: {name}")
        if name.endswith(SECRET_SUFFIXES) or "/.env" in name or "node_modules" in parts:
            problems.append(f"does not belong in the sdist: {name}")
    return problems


def check_dist(report: Report, dist: Path, version: str) -> tuple[Path | None, Path | None]:
    if not dist.is_dir():
        report.add(False, f"{dist} exists", "run with --build, or `python -m build`")
        return None, None
    wheel, sdist, extra = artifacts(dist, version)
    report.add(
        wheel is not None and sdist is not None and not extra,
        "dist/ holds exactly one sdist and one wheel, and nothing else",
        "found: " + ", ".join(p.name for p in sorted(dist.glob("*"))),
    )
    if wheel:
        found = wheel_problems(wheel, version)
        report.add(
            not found, f"wheel {wheel.name}: pure-Python, complete, no junk", "\n".join(found)
        )
    if sdist:
        found = sdist_problems(sdist, version)
        report.add(
            not found, f"sdist {sdist.name}: complete, no fixtures or bulk", "\n".join(found)
        )
    return wheel, sdist


def check_twine(report: Report, dist: Path) -> None:
    files = [str(p) for p in sorted(dist.glob(f"{PACKAGE}-*")) if p.is_file()]
    if not files:
        report.add(False, "twine check --strict", "nothing to check")
        return
    done = run_step([sys.executable, "-m", "twine", "check", "--strict", *files])
    report.add(done.returncode == 0, "twine check --strict", done.stdout + done.stderr)


def check_smoke(report: Report, wheel: Path | None, *, run_smoke: bool) -> None:
    if not run_smoke:
        report.not_run("smoke: the wheel was not installed in a fresh venv (pass --smoke)")
        return
    if wheel is None:
        report.add(False, "smoke: install the wheel in a fresh venv", "no wheel to install")
        return
    done = run_step([sys.executable, "scripts/smoke_wheel.py", str(wheel)])
    tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-8:])
    report.add(done.returncode == 0, "smoke: scripts/smoke_wheel.py passes", tail)


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args_in = sys.argv[1:] if argv is None else argv
    for arg in args_in:
        if arg.startswith("--") and any(word in arg.lower() for word in UPLOAD_WORDS):
            print(
                "refused: this script never uploads. Uploading to PyPI cannot be undone, so it is\n"
                "a separate command you type yourself; see docs/RELEASING.md.",
                file=sys.stderr,
            )
            return 2

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dist", type=Path, default=ROOT / "dist", help="directory to check")
    parser.add_argument("--build", action="store_true", help="rebuild the distributions first")
    parser.add_argument("--gate", action="store_true", help="run scripts/check.py (slow)")
    parser.add_argument("--smoke", action="store_true", help="install the wheel in a fresh venv")
    args = parser.parse_args(args_in)

    if shutil.which("git") is None:
        print("error: git is required", file=sys.stderr)
        return 2

    report = Report()
    print("1. git")
    version_for_tag = read_version()
    check_git(report, version_for_tag)
    print("2. version")
    version = check_version(report)
    print("3. gate")
    check_gate(report, run_gate=args.gate)
    if version is None:
        print("no version, so nothing below can be checked")
        return 1
    print("4. distributions")
    if args.build:
        build(report, args.dist)
    wheel, _ = check_dist(report, args.dist, version)
    print("5. twine")
    check_twine(report, args.dist)
    print("6. install smoke test")
    check_smoke(report, wheel, run_smoke=args.smoke)

    print()
    if report.failed:
        print(f"NOT READY: {len(report.failed)} check(s) failed")
        for label in report.failed:
            print(f"  - {label}")
        return 1
    if report.skipped:
        print("NOT READY: nothing failed, but these were not run:")
        for label in report.skipped:
            print(f"  - {label}")
        return 1
    print(f"READY: {PACKAGE} {version} passed every check. Nothing was uploaded.")
    print("Next: the TestPyPI dry run in docs/RELEASING.md, then the upload, typed by you.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
