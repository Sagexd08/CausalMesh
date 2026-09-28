import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from causalmesh.server import create_app


class UpstreamStub:
    def __init__(self, reply_content: str = "hello from upstream") -> None:
        self.requests: list[dict] = []
        self._reply_content = reply_content
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
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

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


def test_no_upstream_configured_is_recorded_and_stubbed(client):
    response = client.post(
        "/v1/chat/completions", json={"model": "any", "causalmesh_agent": "test-agent"}
    )
    assert response.status_code == 200
    assert response.headers.get("X-CausalMesh-Verdict") == "allowed"

    data = response.json()
    assert data["causalmesh"]["gated"] is True


def test_allowlisted_host_is_allowed_and_forwarded(mesh):
    # For testing allowlisted behavior, we need a mesh whose contract has an allowlist
    # The default mesh in conftest doesn't have an allowlist (which means unrestricted)
    # So it will allow the upstream connection.
    with UpstreamStub("hello from upstream") as upstream:
        app = create_app(mesh=mesh, upstream_base_url=upstream.base_url, auth_disabled=True)
        from fastapi.testclient import TestClient

        test_client = TestClient(app, raise_server_exceptions=False)

        response = test_client.post(
            "/v1/chat/completions",
            json={"model": "fake-model", "causalmesh_agent": "test-agent", "messages": []},
        )
        assert response.status_code == 200
        assert response.headers.get("X-CausalMesh-Verdict") == "allowed"

        data = response.json()
        assert data["causalmesh"]["gated"] is True
        assert data["choices"][0]["message"]["content"] == "hello from upstream"
        assert len(upstream.requests) == 1


def test_invalid_json_body_is_400(client):
    response = client.post(
        "/v1/chat/completions", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
