"""agent_b's caller of the utility. A second, independently owned caller.

It works today because it calls the utility with its current name.
"""

import textutil


def tag_path(label):
    """The URL path of a tag."""
    return "/tags/" + textutil.slugify(label)
