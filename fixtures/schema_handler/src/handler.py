"""Consumes the schema. Must be kept consistent with src/schema.py by hand.

The duplication is deliberate and is the point of the task. If the handler
derived its fields from `schema.FIELDS` it could never fall out of sync, the
integration test could never fail, and the task would measure nothing — a
coordination benchmark needs a dependency a careless agent can actually
break.

An agent that widens the schema must also update HANDLED_FIELDS here. That
is the coordination dependency the four arms are being compared on.
"""

from schema import FIELDS

# Kept in step with schema.FIELDS by hand. See the module docstring.
HANDLED_FIELDS = ["id", "name"]


def build(**values):
    """Build a record from the fields this handler knows about."""
    return {field: values.get(field) for field in HANDLED_FIELDS}


def declared_fields():
    """What the schema currently declares, for the consistency check."""
    return list(FIELDS)
