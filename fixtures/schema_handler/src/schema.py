"""The record schema both agents depend on."""

FIELDS = ["id", "name"]


def validate(record):
    """Return True when a record has exactly the declared fields."""
    return set(record) == set(FIELDS)
