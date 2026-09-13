"""The contested file: both agents need to register themselves here.

This is the concurrent_edit_collision family (spec §35). Unlike the
schema/handler task, where ownership is disjoint and enforcement never has
anything to block, both agents genuinely need to write THIS file — so C3's
claim registry must refuse one of them.

The registry is a plain dict rather than something derived, for the same
reason handler.py duplicates its field list by hand: a value that could
never be wrong cannot demonstrate a coordination failure.
"""

# Each agent registers its own handler name here. Both must end up present
# for the integration test to pass.
REGISTERED = {}


def register(name, handler):
    """Add a handler to the registry."""
    REGISTERED[name] = handler


def registered_names():
    """Every handler currently registered."""
    return sorted(REGISTERED)
