"""The pricing interface. agent_a owns it; agent_b's cart consumes it.

This is the interface_consumer family (spec section 35). The coordination
dependency is a *call shape*: `quote(item)` today, and agent_a's task is to
make quote region-aware, which changes the signature to `quote(item, region)`
with no default.

There is deliberately no compatibility shim and no default argument. A
backward-compatible change could never break a stale caller, the integration
test could never fail, and the task would measure nothing. A coordination
benchmark needs a dependency a careless agent can actually break.
"""

_BASE_PRICES = {"apple": 3, "pear": 2, "plum": 4}


def quote(item):
    """The price of one item."""
    return _BASE_PRICES[item]
