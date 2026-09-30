"""The pricing interface the checkout consumer calls.

This is the interface_consumer family (spec §35). The producer of this
module and the author of its one consumer are different agents. The
producer may change what a caller must pass; the consumer only finds out by
being told, because it calls `format_price` by name and nothing in the
consumer derives the call from this file.

The call is deliberately hand-written on the consumer side. If the consumer
could not fall out of step with this signature, the integration test could
never fail and the task would measure nothing.
"""


def format_price(cents):
    """Render an integer number of cents as a decimal string, e.g. 1250 -> "12.50"."""
    return f"{cents // 100}.{cents % 100:02d}"
