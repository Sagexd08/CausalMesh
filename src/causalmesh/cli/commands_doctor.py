"""`causalmesh doctor` — environment health check (spec §61).

Reports PASS, WARN or FAIL per check with something actionable attached.
A check that only says FAIL has told the operator nothing they could not
see from the failure they already had.

WARN exists for the difference between "this will not work" and "this
works but something is worth knowing" — an unbuilt analysis stack stops
`analyze`, not `run`, and reporting both as FAIL would send someone
hunting for a problem they do not have.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from causalmesh.cli._context import find_root
from causalmesh.cli._output import Exit, emit, out_console, table

MINIMUM_PYTHON = (3, 11)


@dataclass
class Check:
    name: str
    status: str
    detail: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "check": self.name,
            "detail": self.detail,
            "hint": self.hint,
            "status": self.status,
        }


def _python_check() -> Check:
    version = ".".join(str(part) for part in sys.version_info[:3])
    if sys.version_info[:2] < MINIMUM_PYTHON:
        return Check(
            "python",
            "FAIL",
            f"Python {version}",
            f"CausalMesh needs {MINIMUM_PYTHON[0]}.{MINIMUM_PYTHON[1]} or newer.",
        )
    return Check("python", "PASS", f"Python {version}")


def _dependency_check(module: str, *, label: str, optional: bool, hint: str) -> Check:
    try:
        __import__(module)
    except ImportError:
        return Check(label, "WARN" if optional else "FAIL", "not installed", hint)
    return Check(label, "PASS", "installed")


def _root_check(root: Path | None) -> Check:
    if root is None:
        return Check(
            "repository",
            "FAIL",
            "no CausalMesh checkout found",
            "Run from inside the repository, or pass --root.",
        )
    return Check("repository", "PASS", str(root))


def _directory_check(root: Path | None, name: str, relative: str, *, required: bool) -> Check:
    if root is None:
        return Check(name, "WARN", "not checked (no repository root)")
    path = root / relative
    if path.is_dir():
        count = len(list(path.iterdir()))
        return Check(name, "PASS", f"{path} ({count} entries)")
    if required:
        return Check(name, "FAIL", f"{path} is missing", "The checkout looks incomplete.")
    return Check(name, "WARN", f"{path} does not exist yet", "Created on the first run.")


def _tasks_check(root: Path | None) -> Check:
    if root is None:
        return Check("tasks", "WARN", "not checked (no repository root)")
    try:
        from causalmesh.tasks import load_tasks

        tasks = load_tasks(root / "tasks")
    except Exception as exc:  # noqa: BLE001 — doctor reports, never crashes
        return Check(
            "tasks", "FAIL", f"{type(exc).__name__}: {exc}", "Run `causalmesh task validate`."
        )
    if not tasks:
        return Check("tasks", "WARN", "no tasks found", "Nothing to run until a task exists.")
    ids = ", ".join(sorted(task.task_id for task in tasks))
    return Check("tasks", "PASS", f"{len(tasks)} loaded ({ids})")


def _unbuilt_check() -> Check:
    """State plainly which subsystems have no implementation yet.

    This is the honest counterpart to a CLI that offers commands: without
    it, a user discovers the gaps by hitting them. `docs/backlog.md` carries
    the reasons; doctor carries the fact.
    """
    import causalmesh

    package_root = Path(causalmesh.__file__).parent
    unbuilt = []
    # "adversarial" is deliberately absent: the attack battery is a test suite
    # (tests/adversarial) run against the shipped verifier, so an empty
    # src/causalmesh/adversarial/ says nothing about whether it is built.
    for subsystem in ("metrics", "analysis", "reporting", "provenance"):
        directory = package_root / subsystem
        modules = [p for p in directory.glob("*.py") if p.name != "__init__.py"]
        if not modules:
            unbuilt.append(subsystem)
    if not unbuilt:
        return Check("coverage", "PASS", "every subsystem has an implementation")
    blocked = []
    if "reporting" in unbuilt:
        blocked.append("`report`")
    if "provenance" in unbuilt:
        blocked.append("`audit`")
    hint = (
        f"{' and '.join(blocked)} unavailable. See docs/backlog.md."
        if blocked
        else "See docs/backlog.md."
    )
    return Check("coverage", "WARN", f"not built: {', '.join(unbuilt)}", hint)


def doctor_command(
    root_option: Annotated[
        Path | None,
        typer.Option("--root", help="Repository root. Defaults to searching upward from the cwd."),
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Emit machine-readable output.")] = False,
) -> None:
    """Check that this environment can run experiments."""
    root = root_option.resolve() if root_option else find_root()

    checks = [
        _python_check(),
        _root_check(root),
        _dependency_check(
            "cryptography",
            label="cryptography",
            optional=False,
            hint="pip install -e . — Ed25519 signing needs it.",
        ),
        _dependency_check(
            "yaml", label="pyyaml", optional=False, hint="pip install -e . — tasks are YAML."
        ),
        _dependency_check(
            "numpy",
            label="analysis stack",
            optional=True,
            hint="pip install -e '.[analysis]' — only needed once analysis exists.",
        ),
        _directory_check(root, "fixtures", "fixtures", required=True),
        _directory_check(root, "task files", "tasks", required=True),
        _directory_check(root, "raw data", "data/raw", required=False),
        _tasks_check(root),
        _unbuilt_check(),
    ]

    failures = [c for c in checks if c.status == "FAIL"]
    warnings = [c for c in checks if c.status == "WARN"]
    verdict = "FAIL" if failures else ("WARN" if warnings else "PASS")

    payload = {
        "checks": [c.to_dict() for c in checks],
        "failed": len(failures),
        "platform": f"{platform.system()} {platform.release()}",
        "verdict": verdict,
        "warned": len(warnings),
    }
    if not emit(payload, as_json=as_json):
        rendered = table("causalmesh doctor", ["check", "status", "detail"])
        for check in checks:
            colour = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}[check.status]
            rendered.add_row(check.name, f"[{colour}]{check.status}[/{colour}]", check.detail)
        out_console.print(rendered)
        for check in checks:
            if check.hint and check.status != "PASS":
                out_console.print(f"  [dim]{check.name}: {check.hint}[/dim]")

    raise typer.Exit(Exit.FAILED if failures else Exit.OK)
