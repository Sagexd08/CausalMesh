"""SYNTHETIC fixture test, not real CooperBench data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from greeter import GREETINGS, greet  # noqa: E402
from utils import shout  # noqa: E402


def test_greet_casual():
    assert greet("Ada") == "Hi, Ada!"


def test_greet_formal():
    assert "formal" in GREETINGS
    assert greet("Ada", style="formal") == "Good day, Ada!"


def test_shout():
    assert shout("hi") == "HI"
