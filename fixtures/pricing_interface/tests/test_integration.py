"""Integration test: the consumer must still work against the interface.

This is the §38 success criterion. It fails when the pricing interface
changes what a caller must pass and the checkout consumer keeps calling the
old shape. The assertions are on what a receipt must contain, so they hold
both before the interface change and after a consumer that followed it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from checkout import receipt_line, receipt_total  # noqa: E402


def test_a_receipt_line_carries_the_item_and_the_price():
    line = receipt_line("widget", 1250)
    assert line.startswith("widget: 12.50"), f"unexpected receipt line: {line!r}"


def test_the_total_is_the_sum_of_the_items():
    total = receipt_total([("widget", 1250), ("gadget", 250)])
    assert total.startswith("15.00"), f"unexpected total: {total!r}"
