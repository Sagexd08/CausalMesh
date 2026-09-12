"""Integration test: the handler must stay consistent with the schema.

This is the §38 success criterion. It fails when an agent changes the
schema without the handler following — the stale-dependency defect the
coordination channel exists to prevent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from handler import HANDLED_FIELDS, build  # noqa: E402
from schema import FIELDS, validate  # noqa: E402


def test_handler_covers_every_declared_field():
    missing = set(FIELDS) - set(HANDLED_FIELDS)
    extra = set(HANDLED_FIELDS) - set(FIELDS)
    assert not missing and not extra, (
        f"handler is out of step with the schema: missing {sorted(missing)}, "
        f"unexpected {sorted(extra)}"
    )


def test_handler_builds_a_record_the_schema_accepts():
    record = build(**{field: field for field in FIELDS})
    assert validate(record), (
        f"handler produced {sorted(record)} but the schema declares {sorted(FIELDS)}"
    )
