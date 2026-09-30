"""agent_a's own caller of the utility. Whoever refactors must migrate it."""

import textutil


def permalink(title):
    """The URL path of an article."""
    return "/articles/" + textutil.slugify(title)
