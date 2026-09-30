"""First consumer of the shared text utility: query matching."""

from textutil import clean


def matches(query, title):
    """Whether a query appears in a title, ignoring case and outer whitespace."""
    return clean(query) in clean(title)
