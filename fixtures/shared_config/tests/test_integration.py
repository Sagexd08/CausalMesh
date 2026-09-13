"""Both handlers must be registered in the shared config.

The task succeeds only when the two agents' registrations coexist. A
last-writer-wins collision leaves exactly one of them, which is the
divergence this task induces.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from config import REGISTERED, registered_names  # noqa: E402


def test_both_handlers_are_registered():
    assert registered_names() == ["alpha", "beta"], (
        f"expected both handlers, found {registered_names()}"
    )


def test_registrations_point_at_real_handlers():
    for name in registered_names():
        assert callable(REGISTERED[name]), f"{name} is registered but not callable"
