"""Reports over a collection (`docs/PLAN.md` Step 14, labelling only).

`report` tabulates what a collection recorded and applies the interval and
test primitives of `causalmesh.analysis.inference`, labelling every table
PILOT or DERIVED. It does not preregister, confirm or model anything: see
the module docstring and `docs/backlog.md`.
"""

from __future__ import annotations

from .report import (
    EMITTABLE_LABELS,
    LABELS,
    ArmRow,
    ContrastRow,
    Report,
    ReportError,
    build_report,
    render_text,
)

__all__ = [
    "EMITTABLE_LABELS",
    "LABELS",
    "ArmRow",
    "ContrastRow",
    "Report",
    "ReportError",
    "build_report",
    "render_text",
]
