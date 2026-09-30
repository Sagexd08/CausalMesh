"""Consumes the pricing interface. Calls `format_price` by hand.

The consumer owns the call site. When `pricing.format_price` changes what a
caller must pass, this module has to change with it, and it can only know
that if someone tells it. That is the coordination dependency.
"""

from pricing import format_price


def receipt_line(name, cents):
    """One printable receipt line for an item."""
    return f"{name}: {format_price(cents)}"


def receipt_total(items):
    """The printable total for a list of (name, cents) pairs."""
    return format_price(sum(cents for _, cents in items))
