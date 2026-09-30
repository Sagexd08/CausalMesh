"""Integration test: every caller of the utility must use its current shape.

This is the section 38 success criterion. It fails when the utility is
refactored and a caller still uses the old call shape (an AttributeError at
call time), which is the stale-caller defect the coordination channel exists
to prevent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import articles  # noqa: E402
import tags  # noqa: E402
import textutil  # noqa: E402


def test_the_refactor_landed():
    # agent_a's half: the utility takes a separator.
    assert textutil.make_slug("Big Data", sep="_") == "big_data"


def test_the_refactorers_own_caller_was_migrated():
    assert articles.permalink("Hello World") == "/articles/hello-world"


def test_the_other_callers_work_through_the_refactored_utility():
    assert tags.tag_path("Big Data") == "/tags/big-data"
    # agent_b's half: the new feature is built on the same utility.
    assert tags.tag_feed_path("Big Data") == "/tags/big-data/feed"
