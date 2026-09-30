"""A shared utility with more than one caller. agent_a owns it.

This is the shared_utility_refactor family (spec section 35). agent_a's task
is to refactor `slugify` into `make_slug`, which takes a separator. The old
name is removed outright, with no alias left behind.

That is what makes the dependency real. A refactor that leaves a deprecated
alias in place can never break a caller that keeps the old call shape, so
the integration test could never fail and the task would measure nothing.
"""

import re


def slugify(text):
    """Lowercase, hyphen-separated form of a piece of text."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
