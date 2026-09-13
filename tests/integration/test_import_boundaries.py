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

    def test_the_verifier_does_not_import_the_relay(self) -> None:
        """§26: the verifier must run with the relay permanently offline.

        This file's docstring has always named this boundary, but for
        several steps nothing enforced it — and `docs/IDEA.md` claimed it
        was "enforced by a test" when it was not. Offline verification is
        the entire audit story: if the verifier pulled in the relay, an
        auditor would need the very component whose output they are
        checking, and "verifiable independently" would be false.
        """
        loaded = modules_loaded_by("causalmesh.verifier")
        assert not offending(
            loaded,
            (
                "relay",
                "claims",
                "scheduler",
                "storage",
                "agents",
                "adapters",
                "channels",
                "hooks",
                "tools",
                "isolation",
                "tasks",
            ),
        )

    def test_the_verifier_needs_only_events_and_crypto(self) -> None:
        # Stated positively as well: an auditor needs the canonical byte
        # definition and the signature scheme, and nothing else.
        loaded = modules_loaded_by("causalmesh.verifier")
        unexpected = {
            m
            for m in loaded
            if not (
                m == "causalmesh"
                or m.startswith("causalmesh.events")
                or m.startswith("causalmesh.crypto")
                or m.startswith("causalmesh.verifier")
            )
        }
        assert not unexpected, f"verifier gained dependencies: {sorted(unexpected)}"


class TestDesignBoundary:
    """§5: the design must be readable without the runtime."""

    def test_experiments_does_not_import_the_runtime(self) -> None:
        """The analysis layer reads the arm table; it must not drag in agents.

        `experiments/arms.py` describes the design and deliberately does
        not construct anything. If importing it pulled in the runtime, the
        analysis layer could not read the design without loading the
        machinery that produced the data.
        """
        loaded = modules_loaded_by("causalmesh.experiments")
        assert not offending(
            loaded,
            ("relay", "agents", "adapters", "tools", "hooks", "isolation", "channels"),
        )
