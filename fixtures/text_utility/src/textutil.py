"""The shared text utility both consumers import.

This is the shared_utility_refactor family (spec §35). One agent owns this
module and refactors it; two other agents each own a consumer that imports
`clean` by name. A refactor that renames or removes a shared name breaks
every consumer at once, and each consumer can only follow if it is told.

The consumers import the name by hand rather than through an alias layer.
A consumer that could never fall out of step with the utility would make the
integration test impossible to fail, and the task would measure nothing.
"""


def clean(text):
    """Trim surrounding whitespace and lowercase a string."""
    return text.strip().lower()
