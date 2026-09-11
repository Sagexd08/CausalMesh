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