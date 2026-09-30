"""Second consumer of the shared text utility: export keys."""

from textutil import clean


def export_key(label):
    """A normalised key for an exported label."""
    return clean(label).replace(" ", "_")
