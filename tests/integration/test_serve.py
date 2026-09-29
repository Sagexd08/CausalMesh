"""`causalmesh serve`: how the command wires authentication and startup.

The server itself is covered in `tests/server`. What is here is the command:
which flags it accepts, what it refuses to start without, and that `--dev`
never switches a supplied token off. `uvicorn.run` is replaced, so nothing
listens.

This file once also drove `adapters/serve.py`, a stdlib `http.server`
implementation of the same endpoint that nothing reached after `serve` moved
onto FastAPI. It had no authentication and still derived the allowlisted host
by string-splitting, so it was removed, with the tests that existed only for
it, on 2026-09-30.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from typer.testing import CliRunner

from causalmesh.cli.main import app

pytestmark = [pytest.mark.integration]

runner = CliRunner()


class TestCliWiring:
    def test_serve_fails_usage_when_no_contract_is_found(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["serve", "--root", str(tmp_path)])
        assert result.exit_code == 2
        assert "no causalmesh.yaml" in result.output

    def test_serve_dev_on_public_interface_is_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles: []\npolicy:\n  arm: C3\nevidence:\n  sign: false\n"
        )
        result = runner.invoke(
            app, ["serve", "--root", str(tmp_path), "--dev", "--host", "0.0.0.0"]
        )
        assert result.exit_code == 2
        assert "disables authentication" in result.output

    def test_serve_without_dev_requires_token(self, tmp_path: Path) -> None:
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles: []\npolicy:\n  arm: C3\nevidence:\n  sign: false\n"
        )
        result = runner.invoke(app, ["serve", "--root", str(tmp_path)])
        assert result.exit_code == 2
        assert "is required when not in --dev mode" in result.output

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_token_is_no_token_and_never_disables_auth(
        self, tmp_path: Path, blank: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        uvicorn = pytest.importorskip("uvicorn")
        started: list[object] = []
        monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(k))
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles: []\npolicy:\n  arm: C3\nevidence:\n  sign: false\n"
        )
        result = runner.invoke(
            app, ["serve", "--root", str(tmp_path), "--host", "0.0.0.0", "--api-token", blank]
        )
        assert started == [], "the server started with a blank token"
        assert result.exit_code == 2
        assert "is required when not in --dev mode" in result.output

    @staticmethod
    def _serve_and_capture(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
    ) -> tuple[Any, list[Any]]:
        """Run `serve` with uvicorn stubbed out, returning the result and the apps it built."""
        uvicorn = pytest.importorskip("uvicorn")
        pytest.importorskip("fastapi")
        apps: list[Any] = []
        monkeypatch.setattr(uvicorn, "run", lambda application, **_: apps.append(application))
        (tmp_path / "causalmesh.yaml").write_text(
            "version: 1\nroles: []\npolicy:\n  arm: C3\nevidence:\n  sign: false\n"
        )
        return runner.invoke(app, ["serve", "--root", str(tmp_path), *args]), apps

    def test_dev_with_a_token_still_enforces_the_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        result, apps = self._serve_and_capture(
            tmp_path, monkeypatch, ["--dev", "--api-token", "secret"]
        )
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools").status_code == 401
        assert client.get("/v1/tools", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert (
            client.get("/v1/tools", headers={"Authorization": "Bearer secret"}).status_code == 200
        )

    def test_dev_without_a_token_serves_openly_on_localhost(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        result, apps = self._serve_and_capture(tmp_path, monkeypatch, ["--dev"])
        assert result.exit_code == 0, result.output
        assert TestClient(apps[0]).get("/v1/tools").status_code == 200

    def test_a_token_is_enforced_without_dev(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from fastapi.testclient import TestClient

        result, apps = self._serve_and_capture(tmp_path, monkeypatch, ["--api-token", "secret"])
        assert result.exit_code == 0, result.output
        assert TestClient(apps[0]).get("/v1/tools").status_code == 401

    @pytest.mark.parametrize("upstream", ["file:///etc/passwd", "ftp://example.com", "example.com"])
    def test_an_upstream_that_is_not_http_is_a_usage_error_not_a_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, upstream: str
    ) -> None:
        result, apps = self._serve_and_capture(
            tmp_path, monkeypatch, ["--dev", "--upstream", upstream]
        )
        assert apps == [], "the server started with a non-HTTP upstream"
        assert result.exit_code == 2
        assert "upstream" in result.output
        assert "Traceback" not in result.output
