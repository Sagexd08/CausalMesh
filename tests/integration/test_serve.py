"""`causalmesh serve`: the OpenAI-compatible gate-and-record endpoint.

Drives a real `_Server` over a real socket with the stdlib HTTP client,
including a real upstream server for the forwarding tests, rather than
mocking either side.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")
from typer.testing import CliRunner

from causalmesh.adapters.serve import ServeConfig, run_server
from causalmesh.cli.main import app
from causalmesh.crypto.keys import PublicKeyRing
from causalmesh.policy.contract import Contract, Role
from causalmesh.verifier import verify_chain

pytestmark = [pytest.mark.integration]

runner = CliRunner()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _post(
    base_url: str, path: str, body: dict[str, Any]
) -> tuple[int, dict[str, Any], dict[str, str]]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(  # noqa: S310
        base_url + path, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read()), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read()), dict(exc.headers)


def _get(base_url: str, path: str) -> tuple[int, dict[str, Any]]:
    try:
        with urllib.request.urlopen(base_url + path, timeout=10) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


class UpstreamStub:
    """A real chat-completions endpoint on a real socket, for forward tests."""

    def __init__(self, reply_content: str = "hello from upstream") -> None:
        self.requests: list[dict[str, Any]] = []
        self._reply_content = reply_content
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                stub.requests.append(json.loads(raw))
                payload = json.dumps(
                    {
                        "id": "chatcmpl-stub",
                        "object": "chat.completion",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": stub._reply_content},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def __enter__(self) -> UpstreamStub:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class Serving:
    """Starts a real `causalmesh serve` on a background thread."""

    def __init__(self, config: ServeConfig) -> None:
        self.config = config
        self.server = run_server(config, block=False)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(self.base_url + "/healthz", timeout=0.2)  # noqa: S310
                return
            except Exception:
                time.sleep(0.02)
        raise RuntimeError("serve did not come up in time")

    @property
    def base_url(self) -> str:
        return f"http://{self.config.host}:{self.config.port}"

    def records(self) -> list[dict[str, Any]]:
        return self.server._state.relay.records()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def unrestricted_contract(arm: str = "C3") -> Contract:
    return Contract(roles=(Role(agent_id="agent"),), arm=arm)


def allowlisted_contract(*, allow: frozenset[str], arm: str = "C3") -> Contract:
    return Contract(roles=(Role(agent_id="agent", allow=allow),), arm=arm)


class TestHealthAndProtocol:
    def test_healthz_reports_the_run_id(self) -> None:
        config = ServeConfig(
            contract=unrestricted_contract(), run_id="run_health", port=_free_port()
        )
        s = Serving(config)
        try:
            status, payload = _get(s.base_url, "/healthz")
            assert status == 200
            assert payload == {"ok": True, "run_id": "run_health"}
        finally:
            s.close()

    def test_unknown_path_is_404(self) -> None:
        config = ServeConfig(contract=unrestricted_contract(), run_id="run_404", port=_free_port())
        s = Serving(config)
        try:
            status, _, _ = _post(s.base_url, "/v1/completions", {})
            assert status == 404
            status, _ = _get(s.base_url, "/nope")
            assert status == 404
        finally:
            s.close()

    def test_invalid_json_body_is_400(self) -> None:
        config = ServeConfig(contract=unrestricted_contract(), run_id="run_400", port=_free_port())
        s = Serving(config)
        try:
            req = urllib.request.Request(  # noqa: S310
                s.base_url + "/v1/chat/completions",
                data=b"{not json",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(req, timeout=10)  # noqa: S310
                pytest.fail("expected an HTTPError")
            except urllib.error.HTTPError as exc:
                assert exc.code == 400
        finally:
            s.close()


class TestGateAndRecord:
    def test_no_upstream_configured_is_recorded_and_stubbed(self) -> None:
        config = ServeConfig(contract=unrestricted_contract(), run_id="run_stub", port=_free_port())
        s = Serving(config)
        try:
            status, payload, headers = _post(
                s.base_url, "/v1/chat/completions", {"model": "any", "causalmesh_agent": "agent"}
            )
            assert status == 200
            assert headers.get("X-CausalMesh-Verdict") == "allowed"
            assert payload["causalmesh"]["gated"] is True
            records = s.records()
            assert len(records) == 1
            assert records[0]["event"]["event_type"] == "INTENT"
            assert records[0]["event"]["identity"]["agent_id"] == "agent"
        finally:
            s.close()

    def test_allowlisted_host_is_allowed_and_forwarded(self) -> None:
        # The allowlist entry is a bare host; the gate strips port/path from
        # the resource before matching (tests/unit/test_policy.py::TestAllowlist).
        with UpstreamStub("hello from upstream") as upstream:
            config = ServeConfig(
                contract=allowlisted_contract(allow=frozenset({"127.0.0.1"})),
                run_id="run_allow",
                port=_free_port(),
                upstream_base_url=upstream.base_url,
            )
            s = Serving(config)
            try:
                status, payload, headers = _post(
                    s.base_url,
                    "/v1/chat/completions",
                    {"model": "fake-model", "causalmesh_agent": "agent", "messages": []},
                )
                assert status == 200
                assert headers.get("X-CausalMesh-Verdict") == "allowed"
                assert payload["causalmesh"]["gated"] is True
                assert payload["choices"][0]["message"]["content"] == "hello from upstream"
                assert len(upstream.requests) == 1

                records = s.records()
                assert records[0]["event"]["event_type"] == "INTENT"
                key_ring = PublicKeyRing.from_keypairs(s.server._state.relay._keypairs)
                assert verify_chain(records, key_ring).valid
            finally:
                s.close()

    def test_unlisted_host_is_refused_as_402_and_recorded(self) -> None:
        with UpstreamStub() as upstream:
            config = ServeConfig(
                contract=allowlisted_contract(allow=frozenset({"api.allowed.example"})),
                run_id="run_refuse",
                port=_free_port(),
                upstream_base_url=upstream.base_url,
            )
            s = Serving(config)
            try:
                status, payload, headers = _post(
                    s.base_url,
                    "/v1/chat/completions",
                    {"model": "fake-model", "causalmesh_agent": "agent"},
                )
                assert status == 402
                assert headers.get("X-CausalMesh-Verdict") == "refused"
                assert payload["error"]["type"] == "causalmesh_refused"
                assert upstream.requests == []

                records = s.records()
                assert len(records) == 1
                assert records[0]["event"]["event_type"] == "FAILURE"
                assert records[0]["event"]["payload"]["allowed"] is False
            finally:
                s.close()

    def test_c2_does_not_enforce_but_still_records_the_shadow_verdict(self) -> None:
        with UpstreamStub() as upstream:
            config = ServeConfig(
                contract=allowlisted_contract(allow=frozenset({"api.allowed.example"}), arm="C2"),
                run_id="run_c2",
                port=_free_port(),
                upstream_base_url=upstream.base_url,
            )
            s = Serving(config)
            try:
                status, _, headers = _post(
                    s.base_url,
                    "/v1/chat/completions",
                    {"model": "fake-model", "causalmesh_agent": "agent"},
                )
                assert status == 200
                assert headers.get("X-CausalMesh-Verdict") == "allowed"
                records = s.records()
                assert records[0]["event"]["event_type"] == "INTENT"
                assert "would have refused" in records[0]["event"]["payload"]["reason"]
            finally:
                s.close()

    def test_default_agent_is_used_when_the_body_names_none(self) -> None:
        config = ServeConfig(
            contract=unrestricted_contract(),
            run_id="run_default",
            port=_free_port(),
            default_agent="agent",
        )
        s = Serving(config)
        try:
            status, _, _ = _post(s.base_url, "/v1/chat/completions", {"model": "any"})
            assert status == 200
            assert s.records()[0]["event"]["identity"]["agent_id"] == "agent"
        finally:
            s.close()


class TestUpstreamFailure:
    def test_an_unreachable_upstream_reports_an_error_but_the_endpoint_stays_up(self) -> None:
        dead_port = _free_port()
        config = ServeConfig(
            contract=allowlisted_contract(allow=frozenset({"127.0.0.1"})),
            run_id="run_dead",
            port=_free_port(),
            upstream_base_url=f"http://127.0.0.1:{dead_port}",
        )
        s = Serving(config)
        try:
            status, payload, _ = _post(
                s.base_url, "/v1/chat/completions", {"model": "any", "causalmesh_agent": "agent"}
            )
            assert status == 200
            assert "upstream unreachable" in payload["error"]["message"]
            status, _ = _get(s.base_url, "/healthz")
            assert status == 200
        finally:
            s.close()


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
        assert "--api-token is required" in result.output
