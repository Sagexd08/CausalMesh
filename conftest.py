"""Pytest configuration: make the src/ layout importable.

pyproject sets `pythonpath = ["src"]`, but declaring it here too means the
suite runs from a clean clone with no install step, which the reproducibility
requirement (spec §95) depends on.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Test-support modules are imported by bare name from any test directory
# (`from fake_model_server import FakeModelServer`). Pytest only puts a
# directory on sys.path when a test in that same directory imports from it,
# and the fake model server is used from tests/integration/ — so it is
# registered here rather than relying on that.
SUPPORT = Path(__file__).resolve().parent / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
