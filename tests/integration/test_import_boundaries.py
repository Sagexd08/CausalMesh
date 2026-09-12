"""Architectural boundary enforcement (spec §5, §26).

The system's separation of runtime, coordination, measurement, verification
and analysis is only real if it is mechanically enforced. A comment saying
"the verifier must not depend on the relay" decays the first time someone adds
a convenient import; this test does not.

Each boundary is checked in a *subprocess* with a clean interpreter, because
`sys.modules` in the test process is already polluted by every other test.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

pytestmark = pytest.mark.integration


def modules_loaded_by(import_target: str) -> set[str]:
    """Return the causalmesh modules pulled in by importing one module."""
    program = (
        "import sys, json;"
        f"import {import_target};"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('causalmesh'))))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"importing {import_target} failed:\n{result.stderr}"
    return set(json.loads(result.stdout))


def offending(loaded: set[str], forbidden_suffixes: tuple[str, ...]) -> set[str]:
    return {
        module
        for module in loaded
        for suffix in forbidden_suffixes
        if module == f"causalmesh.{suffix}" or module.startswith(f"causalmesh.{suffix}.")
    }


class TestVerificationStack:
    """§26: verification must work with the relay permanently offline."""

    def test_events_depends_on_nothing_internal(self) -> None:
        # The canonical byte definition sits at the bottom of the stack. If it
        # ever gains an internal dependency, that dependency's behaviour could
        # change the bytes every signature in the system is computed over.
        loaded = modules_loaded_by("causalmesh.events")
        assert loaded == {"causalmesh", "causalmesh.events"} | {
            m for m in loaded if m.startswith("causalmesh.events.")
        }

    def test_crypto_depends_only_on_events(self) -> None:
        loaded = modules_loaded_by("causalmesh.crypto")
        unexpected = {
            m
            for m in loaded
            if not (
                m == "causalmesh"
                or m.startswith("causalmesh.events")
                or m.startswith("causalmesh.crypto")
            )
        }
        assert not unexpected, f"crypto gained unexpected dependencies: {sorted(unexpected)}"

    def test_crypto_does_not_import_the_runtime(self) -> None:
        loaded = modules_loaded_by("causalmesh.crypto")
        assert not offending(
            loaded, ("relay", "scheduler", "agents", "adapters", "analysis", "reporting")
        )
