"""Integration test: both consumers must still import and work.

This is the §38 success criterion. A consumer left importing a name the
refactored utility no longer provides fails at import, so the whole module
errors rather than one assertion failing. The assertions are on behaviour, so
they hold before the refactor and after consumers that followed it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from exporter import export_key  # noqa: E402
from search import matches  # noqa: E402


def test_search_ignores_case_and_outer_whitespace():
    assert matches("  Widget ", "The widget Catalogue")
    assert not matches("gadget", "The widget Catalogue")


def test_export_keys_are_normalised():
    assert export_key("  Total Sales ") == "total_sales"
