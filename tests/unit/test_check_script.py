"""The local gate must keep pointing at things that exist.

`scripts/check.py` replaced the CI workflow as the only enforcement. Its
failure mode is quiet: a renamed package leaves a path in the list that mypy
reports as an error nobody expected, or one that a typo makes match nothing.
These tests fail when the list drifts from the tree, and pin the one property
that makes the gate honest: a missing tool is a failure, not a skip.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_script", ROOT / "scripts" / "check.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_enforced_mypy_path_is_a_package_in_the_tree() -> None:
    check = _load()
    for path in check.MYPY_ENFORCED:
        assert (ROOT / path / "__init__.py").is_file(), f"{path} is not a package"


def test_the_gate_runs_lint_format_types_security_and_the_suite() -> None:
    labels = [label for label, _, _ in _load().steps(fast=False)]
    assert labels == [
        "ruff check",
        "ruff format",
        "mypy (enforced modules)",
        "bandit",
        "pytest",
    ]


def test_fast_skips_only_the_integration_tests() -> None:
    check = _load()
    full = dict((label, argv) for label, _, argv in check.steps(fast=False))["pytest"]
    fast = dict((label, argv) for label, _, argv in check.steps(fast=True))["pytest"]
    assert "--ignore=tests/integration" not in full
    assert "--ignore=tests/integration" in fast


@pytest.fixture
def nothing_installed(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, list[object]]:
    """The script with every tool reported missing and `subprocess.run` recorded.

    The script's own module references are replaced, not the global ones:
    patching `importlib.util.find_spec` itself would change what pytest sees.
    """
    check = _load()
    ran: list[object] = []
    monkeypatch.setattr(
        check, "importlib", SimpleNamespace(util=SimpleNamespace(find_spec=lambda name: None))
    )
    monkeypatch.setattr(check, "subprocess", SimpleNamespace(run=lambda *a, **k: ran.append(a)))
    return check, ran


def test_a_missing_tool_fails_the_gate_rather_than_skipping_it(
    nothing_installed: tuple[ModuleType, list[object]], capsys: pytest.CaptureFixture[str]
) -> None:
    check, ran = nothing_installed

    assert check.main([]) == 1
    assert ran == [], "a step ran although its tool was reported missing"
    assert "FAILED: ruff check, ruff format, mypy" in capsys.readouterr().out


def test_the_gate_output_is_ascii(
    nothing_installed: tuple[ModuleType, list[object]], capsys: pytest.CaptureFixture[str]
) -> None:
    check, _ = nothing_installed
    check.main([])
    capsys.readouterr().out.encode("ascii")
