"""`causalmesh serve`: token expiry and the tokens file, as the command wires them.

`uvicorn.run` is replaced, so nothing listens. What is checked is what the
command builds (the app's credentials), what it refuses to start with, that no
secret is echoed in a refusal, and that SIGHUP is wired to a reload and unwired
again afterwards. The behaviour of the credentials themselves is in
`tests/server/test_token_lifecycle.py`.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
import uvicorn
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from causalmesh.cli.main import app

pytestmark = [pytest.mark.integration]

runner = CliRunner()

CONTRACT = (
    "version: 1\nroles:\n  - agent_id: coder\n    archetype: writer\n    owns: [src/]\n"
    "policy:\n  arm: C3\nevidence:\n  sign: true\n"
)
TOKEN = "coder-token-0000000000000000"
OTHER = "operator-token-0000000000000"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _serve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *args: str, during: Any = None
) -> tuple[Any, list[Any]]:
    apps: list[Any] = []

    def run(application: Any, **_: Any) -> None:
        apps.append(application)
        if during is not None:
            during(application)

    monkeypatch.setattr(uvicorn, "run", run)
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT)
    return runner.invoke(app, ["serve", "--root", str(tmp_path), *args]), apps


def _tokens_file(tmp_path: Path, entries: list[dict[str, Any]], mode: int = 0o600) -> Path:
    path = tmp_path / "tokens.json"
    path.write_text(json.dumps({"version": 1, "tokens": entries}), encoding="utf-8")
    os.chmod(path, mode)
    return path


def _future(seconds: int = 3600) -> str:
    return str(int(time.time()) + seconds)


class TestExpiryFlags:
    def test_an_agent_token_with_a_future_expiry_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(tmp_path, monkeypatch, "--agent-token", f"coder={TOKEN}@{_future()}")
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(TOKEN)).status_code == 200
        assert client.get("/v1/tools", headers=_auth(f"{TOKEN}@{_future()}")).status_code == 401

    def test_the_expiry_is_enforced_by_the_servers_clock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(tmp_path, monkeypatch, "--agent-token", f"coder={TOKEN}@{_future(5)}")
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        store = apps[0].state.credentials
        (cred,) = store.credentials()
        assert cred.label == "agent-token:coder" and cred.agent_id == "coder"
        assert cred.expires_at is not None and cred.expired(cred.expires_at)
        assert not cred.expired(cred.expires_at - 0.001)
        assert client.get("/v1/tools", headers=_auth(TOKEN)).status_code == 200

    def test_an_already_expired_token_is_a_usage_error_and_not_echoed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(tmp_path, monkeypatch, "--agent-token", f"coder={TOKEN}@1000000000")
        assert result.exit_code == 2
        assert "already expired" in result.output
        assert TOKEN not in result.output
        assert apps == []

    def test_a_token_with_an_at_sign_and_no_expiry_is_left_whole(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        odd = "user@example.com-token-000000"
        result, apps = _serve(tmp_path, monkeypatch, "--agent-token", f"coder={odd}")
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(odd)).status_code == 200

    def test_an_impossible_date_is_refused_not_folded_into_the_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, _ = _serve(tmp_path, monkeypatch, "--agent-token", f"coder={TOKEN}@2026-13-45")
        assert result.exit_code == 2
        assert TOKEN not in result.output

    def test_the_api_token_can_expire_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(
            tmp_path,
            monkeypatch,
            "--api-token",
            OTHER,
            "--api-token-expires",
            "2099-01-01T00:00:00Z",
        )
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(OTHER)).status_code == 200
        assert apps[0].state.credentials.credentials()[0].label == "api-token"

    def test_an_expired_api_token_is_refused_at_startup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, _ = _serve(
            tmp_path, monkeypatch, "--api-token", OTHER, "--api-token-expires", "2001-01-01"
        )
        assert result.exit_code == 2
        assert OTHER not in result.output

    def test_an_expiry_with_no_token_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, _ = _serve(tmp_path, monkeypatch, "--dev", "--api-token-expires", "2099-01-01")
        assert result.exit_code == 2
        assert "needs --api-token" in result.output

    def test_plain_flags_behave_exactly_as_before(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(
            tmp_path, monkeypatch, "--api-token", OTHER, "--agent-token", f"coder={TOKEN}"
        )
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(OTHER)).status_code == 200
        assert client.get("/v1/tools", headers=_auth(TOKEN)).status_code == 200
        assert client.get("/v1/tools").status_code == 401
        assert all(c.expires_at is None for c in apps[0].state.credentials.credentials())


class TestTokensFileFlag:
    def test_a_tokens_file_alone_is_enough_to_serve(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _tokens_file(
            tmp_path, [{"id": "coder-1", "token": TOKEN, "agent": "coder", "expires": _future()}]
        )
        result, apps = _serve(tmp_path, monkeypatch, "--tokens-file", str(path))
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(TOKEN)).status_code == 200
        assert client.get("/v1/tools").status_code == 401
        assert TOKEN not in result.output

    def test_dev_with_a_tokens_file_still_enforces_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _tokens_file(tmp_path, [{"id": "op", "token": OTHER}])
        result, apps = _serve(tmp_path, monkeypatch, "--dev", "--tokens-file", str(path))
        assert result.exit_code == 0, result.output
        assert TestClient(apps[0]).get("/v1/tools").status_code == 401

    def test_a_missing_file_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(tmp_path, monkeypatch, "--tokens-file", str(tmp_path / "nope.json"))
        assert result.exit_code == 2
        assert apps == []

    def test_a_malformed_file_is_a_usage_error_and_its_content_is_not_echoed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "tokens.json"
        path.write_text("tokens: [ leaky-secret-value-0000000", encoding="utf-8")
        os.chmod(path, 0o600)
        result, apps = _serve(tmp_path, monkeypatch, "--tokens-file", str(path))
        assert result.exit_code == 2
        assert "leaky-secret-value" not in result.output
        assert apps == []

    @pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits")
    def test_a_world_readable_file_is_refused_with_the_fix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _tokens_file(tmp_path, [{"id": "op", "token": OTHER}], mode=0o644)
        result, apps = _serve(tmp_path, monkeypatch, "--tokens-file", str(path))
        assert result.exit_code == 2
        assert "chmod 600" in result.output.replace("\n", " ")
        assert OTHER not in result.output
        assert apps == []

    def test_the_tokens_file_path_can_come_from_the_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _tokens_file(tmp_path, [{"id": "op", "token": OTHER}])
        monkeypatch.setenv("CAUSALMESH_TOKENS_FILE", str(path))
        result, apps = _serve(tmp_path, monkeypatch)
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(OTHER)).status_code == 200

    def test_no_token_source_at_all_is_still_refused_without_dev(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = _serve(tmp_path, monkeypatch)
        assert result.exit_code == 2
        assert apps == []


@pytest.mark.skipif(not hasattr(signal, "SIGHUP"), reason="POSIX only")
class TestSighup:
    def test_sighup_makes_the_server_re_read_the_file_and_is_unwired_afterwards(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = _tokens_file(tmp_path, [{"id": "one-aa", "token": "c" * 28}])
        old = 1_000_000_000 * 10**9
        os.utime(path, ns=(old, old))
        before = signal.getsignal(signal.SIGHUP)
        seen: dict[str, int] = {}

        def during(application: Any) -> None:
            client = TestClient(application, raise_server_exceptions=False)
            _tokens_file(tmp_path, [{"id": "two-bb", "token": "d" * 28}])
            os.utime(path, ns=(old, old))  # looks unchanged: only the signal can reveal it
            seen["before_signal"] = client.get("/v1/tools", headers=_auth("d" * 28)).status_code
            os.kill(os.getpid(), signal.SIGHUP)
            seen["after_signal"] = client.get("/v1/tools", headers=_auth("d" * 28)).status_code
            seen["revoked"] = client.get("/v1/tools", headers=_auth("c" * 28)).status_code

        result, _ = _serve(tmp_path, monkeypatch, "--tokens-file", str(path), during=during)
        assert result.exit_code == 0, result.output
        assert seen == {"before_signal": 401, "after_signal": 200, "revoked": 401}
        assert signal.getsignal(signal.SIGHUP) == before
