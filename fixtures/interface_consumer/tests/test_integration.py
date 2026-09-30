"""Integration test: the cart must call pricing with its current signature.

This is the section 38 success criterion. It fails when the interface
changes and a consumer still calls it the old way (a TypeError at call
time), which is the stale-caller defect the coordination channel exists to
prevent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import cart  # noqa: E402
import pricing  # noqa: E402


def test_the_interface_change_landed():
    # agent_a's half: quote is region-aware.
    assert pricing.quote("apple", "eu") == pricing.quote("apple", "us") + 1


def test_the_cart_totals_through_the_current_interface():
    assert cart.total(["apple", "pear"]) == 5


def test_the_cart_has_a_receipt_through_the_current_interface():
    # agent_b's half: the new feature is built on the same interface.
    assert cart.receipt(["apple", "pear"]) == [("apple", 3), ("pear", 2)]
