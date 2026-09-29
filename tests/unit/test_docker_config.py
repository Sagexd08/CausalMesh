"""The container's safety properties, as text, so they cannot be dropped quietly.

A real build and run is how these are verified (the audit does that by hand,
and `docs/backlog.md` says so). What these tests hold is the part a refactor
could lose without anything failing: the image does not run as root, it
declares a health check, and neither it nor the compose file can start the
server without authentication.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def _instructions(text: str) -> list[str]:
    """Dockerfile instructions with continuations joined and comments dropped."""
    joined: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1].strip() + " "
            continue
        joined.append(pending + line)
        pending = ""
    return joined


def test_the_image_does_not_run_as_root() -> None:
    users = [
        i.split(None, 1)[1] for i in _instructions(DOCKERFILE) if i.upper().startswith("USER ")
    ]
    assert users, "no USER instruction: the process runs as root"
    assert users[-1].strip().lower() not in {"root", "0", "0:0", "root:root"}


def test_the_user_is_declared_after_the_install_and_before_the_entrypoint() -> None:
    kinds = [i.split(None, 1)[0].upper() for i in _instructions(DOCKERFILE)]
    assert kinds.index("USER") > max(i for i, k in enumerate(kinds) if k == "RUN")
    assert kinds.index("USER") < kinds.index("ENTRYPOINT")


def test_a_health_check_is_declared_and_needs_no_token() -> None:
    checks = [i for i in _instructions(DOCKERFILE) if i.upper().startswith("HEALTHCHECK ")]
    assert len(checks) == 1
    assert "/health" in checks[0]
    assert "Authorization" not in checks[0]


def test_the_image_cannot_start_the_server_unauthenticated() -> None:
    entrypoint = next(i for i in _instructions(DOCKERFILE) if i.upper().startswith("ENTRYPOINT"))
    assert "--dev" not in entrypoint
    assert "--host" in entrypoint and "0.0.0.0" in entrypoint


def test_the_compose_file_passes_the_token_and_never_asks_for_dev_mode() -> None:
    assert "CAUSALMESH_API_TOKEN" in COMPOSE
    assert "--dev" not in COMPOSE.replace("`--dev`", "").replace("--dev mode", "")
    assert ":ro" in COMPOSE, "the contract must be mounted read-only"
