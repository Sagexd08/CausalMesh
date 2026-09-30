"""agent_b's module: consumes pricing.quote.

Today it works, because it calls quote() with the current signature. It
keeps working only if whoever rewrites it knows the signature has changed.
"""

import pricing


def total(items):
    """The summed price of every item."""
    return sum(pricing.quote(item) for item in items)
