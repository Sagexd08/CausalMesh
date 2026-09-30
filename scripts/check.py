"""The local gate: everything that must be true before a change is merged.

The project used to enforce these in CI. There is no CI now, so this script is
the only enforcement, and it runs the same commands over the same scope:

    python scripts/check.py           # lint, format, types, security, full suite
    python scripts/check.py --fast    # the same, without the subprocess tests

Two decisions are recorded here because they used to live only in the
workflow file, and a rule nobody can find is a rule nobody follows:

**mypy is enforced on the modules that carry the guarantees, not on the
tree.** The chain, the claim registry, the gate, the verifier and the hooks
are clean under `disallow_untyped_defs` and must stay that way; the rest of
the tree predates a strict pass (`mypy src` reports the count). Gating all of
it would block every change on debt unrelated to it.

**A tool that is not installed is a failure, not a skip.** A gate that quietly
passes because `bandit` is missing certifies nothing.

**So is an optional dependency the tests need.** The server, adapter and
analysis tests `importorskip` their extras, so on a machine without them the
suite passes while skipping exactly the tests that cover the authentication
boundary and the framework adapters. The last step names what is missing.

Output is ASCII: Windows consoles default to cp1252 (AGENTS.md).
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MYPY_ENFORCED = (
    "src/causalmesh/crypto",
    "src/causalmesh/claims",
    "src/causalmesh/events",
    "src/causalmesh/verifier",
    "src/causalmesh/policy",
    "src/causalmesh/hooks",
)


# Modules whose absence makes tests skip rather than fail. Each entry is a tuple
# of alternatives: one of them must import.
TEST_DEPENDENCIES: tuple[tuple[str, ...], ...] = (
    ("fastapi",),
    ("uvicorn",),
    ("httpx", "httpx2"),
    ("langchain_core",),
    ("pydantic",),
    ("numpy",),
    ("pandas",),
    ("scipy",),
    ("statsmodels",),
    ("matplotlib",),
    ("hypothesis",),
)


def missing_test_dependencies() -> list[str]:
    """The optional test dependencies that cannot be imported."""
    return [
        " or ".join(alternatives)
        for alternatives in TEST_DEPENDENCIES
        if all(importlib.util.find_spec(name) is None for name in alternatives)
    ]


def steps(*, fast: bool) -> list[tuple[str, str, list[str]]]:
    """(label, python module that must be importable, argv after `python -m`)."""
    suite = ["-q", "--ignore=tests/integration"] if fast else ["-q"]
    return [
        ("ruff check", "ruff", ["ruff", "check", "src", "tests"]),
        ("ruff format", "ruff", ["ruff", "format", "--check", "src", "tests"]),
        ("mypy (enforced modules)", "mypy", ["mypy", *MYPY_ENFORCED]),
        ("bandit", "bandit", ["bandit", "-r", "src", "-ll", "-ii", "-q"]),
        ("pytest", "pytest", ["pytest", *suite]),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fast", action="store_true", help="skip tests/integration")
    args = parser.parse_args(argv)

    results: list[tuple[str, str, float]] = []
    for label, module, command in steps(fast=args.fast):
        print(f"\n=== {label}", flush=True)
        if importlib.util.find_spec(module) is None:
            print(f"not installed: pip install -e '.[dev]'  (missing: {module})")
            results.append((label, "FAIL", 0.0))
            continue
        started = time.monotonic()
        code = subprocess.run([sys.executable, "-m", *command], cwd=ROOT).returncode
        results.append((label, "PASS" if code == 0 else "FAIL", time.monotonic() - started))

    print("\n=== test dependencies", flush=True)
    missing = missing_test_dependencies()
    if missing:
        print(f"not installed: {', '.join(missing)}")
        print(
            "those tests skip instead of failing: pip install -e '.[dev,server,analysis,langchain]'"
        )
    else:
        print("all present: no test is skipped for want of an extra")
    results.append(("test dependencies", "FAIL" if missing else "PASS", 0.0))

    print("\n=== summary")
    for label, status, seconds in results:
        print(f"{status:<5} {label:<26} {seconds:6.1f}s")
    failed = [label for label, status, _ in results if status != "PASS"]
    print("\nALL CHECKS PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
