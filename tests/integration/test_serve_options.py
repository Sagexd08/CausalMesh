"""`causalmesh serve` options that shape the process rather than the policy.

`uvicorn.run` is replaced by a recorder, so nothing listens: what is checked
is what the command *asks uvicorn to do*, and what it refuses to ask for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
import uvicorn
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from causalmesh.cli.main import app
from tls_certs import make_cert

pytestmark = [pytest.mark.integration]

runner = CliRunner()

CONTRACT = "version: 1\nroles: []\npolicy:\n  arm: C3\nevidence:\n  sign: false\n"


class Recorder:
    def __init__(self) -> None:
        self.apps: list[Any] = []
        self.kwargs: list[dict[str, Any]] = []

    def __call__(self, application: Any, **kwargs: Any) -> None:
        self.apps.append(application)
        self.kwargs.append(kwargs)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(uvicorn, "run", rec)
    return rec


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    return tmp_path


def serve(root: Path, *args: str, env: dict[str, str] | None = None):
    return runner.invoke(
        app, ["serve", "--root", str(root), "--api-token", "t" * 20, *args], env=env
    )


class TestWorkers:
    @pytest.mark.parametrize("workers", ["0", "2", "8", "-1"])
    def test_more_than_one_worker_is_refused_with_the_reason(
        self, root: Path, recorder: Recorder, workers: str
    ) -> None:
        result = serve(root, "--workers", workers)
        assert result.exit_code == 2
        assert recorder.apps == [], "the server started with an unsupported worker count"
        assert "not supported" in result.output
        assert "evidence chain" in " ".join(result.output.split())

    def test_one_worker_is_fine(self, root: Path, recorder: Recorder) -> None:
        assert serve(root, "--workers", "1").exit_code == 0
        assert "workers" not in recorder.kwargs[0], "uvicorn must never be asked for workers"


class TestUvicornSettings:
    def test_defaults(self, root: Path, recorder: Recorder) -> None:
        assert serve(root).exit_code == 0
        kwargs = recorder.kwargs[0]
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8420
        assert kwargs["access_log"] is False, "uvicorn's access log would bypass ours"
        assert kwargs["timeout_keep_alive"] == 5
        assert kwargs["timeout_graceful_shutdown"] == 10
        assert "ssl_certfile" not in kwargs

    def test_timeouts_are_configurable(self, root: Path, recorder: Recorder) -> None:
        result = serve(root, "--timeout-keep-alive", "30", "--timeout-graceful-shutdown", "2")
        assert result.exit_code == 0
        assert recorder.kwargs[0]["timeout_keep_alive"] == 30
        assert recorder.kwargs[0]["timeout_graceful_shutdown"] == 2

    @pytest.mark.parametrize(
        "bad", [["--timeout-keep-alive", "0"], ["--timeout-graceful-shutdown", "0"]]
    )
    def test_a_zero_timeout_is_refused(
        self, root: Path, recorder: Recorder, bad: list[str]
    ) -> None:
        assert serve(root, *bad).exit_code == 2
        assert recorder.apps == []

    def test_an_unknown_log_level_is_refused(self, root: Path, recorder: Recorder) -> None:
        result = serve(root, "--log-level", "loud")
        assert result.exit_code == 2
        assert recorder.apps == []

    def test_port_and_host_can_come_from_the_environment(
        self, root: Path, recorder: Recorder
    ) -> None:
        result = serve(root, env={"CAUSALMESH_PORT": "9911", "CAUSALMESH_HOST": "127.0.0.1"})
        assert result.exit_code == 0, result.output
        assert recorder.kwargs[0]["port"] == 9911

    def test_the_flag_wins_over_the_environment(self, root: Path, recorder: Recorder) -> None:
        serve(root, "--port", "9922", env={"CAUSALMESH_PORT": "9911"})
        assert recorder.kwargs[0]["port"] == 9922

    def test_tls_is_passed_through_and_the_passphrase_is_not_in_argv(
        self, root: Path, recorder: Recorder
    ) -> None:
        cert, key = make_cert(root, password=b"pw-from-env-1")
        result = serve(
            root,
            "--ssl-certfile",
            str(cert),
            "--ssl-keyfile",
            str(key),
            env={"CAUSALMESH_SSL_KEYFILE_PASSWORD": "pw-from-env-1"},
        )
        assert result.exit_code == 0, result.output
        kwargs = recorder.kwargs[0]
        assert kwargs["ssl_certfile"] == str(cert)
        assert kwargs["ssl_keyfile"] == str(key)
        assert kwargs["ssl_keyfile_password"] == "pw-from-env-1"
        assert "pw-from-env-1" not in result.output
        assert "https://" in result.output

    def test_there_is_no_command_line_option_for_the_passphrase(self) -> None:
        result = runner.invoke(app, ["serve", "--help"])
        assert "CAUSALMESH_SSL_KEYFILE_PASSWORD" in " ".join(result.output.split())
        assert "--ssl-keyfile-password" not in result.output

    def test_logging_is_restored_after_the_server_returns(
        self, root: Path, recorder: Recorder
    ) -> None:
        import logging

        logger = logging.getLogger("causalmesh")
        before = (list(logger.handlers), logger.level, logger.propagate)
        assert serve(root).exit_code == 0
        assert (list(logger.handlers), logger.level, logger.propagate) == before


class TestDefaultAgentFromTheContract:
    def test_agent_id_in_the_contract_is_the_servers_default_agent(
        self, root: Path, recorder: Recorder
    ) -> None:
        (root / "causalmesh.yaml").write_text(
            "version: 1\nagent:\n  id: coder\nroles:\n  - agent_id: coder\n    owns: [src/]\n"
            "policy:\n  arm: C3\nevidence:\n  sign: false\n",
            encoding="utf-8",
        )
        assert serve(root).exit_code == 0
        assert recorder.apps[0].state.mesh.agent_id == "coder"

    def test_without_it_the_default_is_unchanged(self, root: Path, recorder: Recorder) -> None:
        assert serve(root).exit_code == 0
        assert recorder.apps[0].state.mesh.agent_id == "agent"


class TestOutputIsAscii:
    def test_the_startup_banner_is_ascii(self, root: Path, recorder: Recorder) -> None:
        result = serve(root, "--host", "0.0.0.0")
        assert result.exit_code == 0
        result.output.encode("ascii")  # a cp1252 console must not raise mid-render


def test_the_recorded_app_answers_readiness(root: Path, recorder: Recorder) -> None:
    assert serve(root).exit_code == 0
    assert TestClient(recorder.apps[0]).get("/readyz").json() == {"status": "ready"}
