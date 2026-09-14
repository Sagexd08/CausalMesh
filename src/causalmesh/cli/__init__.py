"""The `causalmesh` command line (spec §62).

The entry point lives in `main.py`; importing it here would pull typer in
for anyone who imports the package, so it is deliberately not re-exported.
"""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """Deferred import so `import causalmesh.cli` stays cheap."""
    from causalmesh.cli.main import main as _main

    _main()
