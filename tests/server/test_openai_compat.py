import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi.testclient import TestClient

from causalmesh import CausalMesh
from causalmesh.policy.contract import Contract
from causalmesh.server import create_app

pytestmark = pytest.mark.integration


class UpstreamStub:
    def __init__(
        self, reply_content: str = "hello from upstream", raw_body: bytes | None = None
    ) -> None:
        self.requests: list[dict] = []
        self.headers: list[dict[str, str]] = []
        self._reply_content = reply_content
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                stub.requests.append(json.loads(raw))
                stub.headers.append({k.lower(): v for k, v in self.headers.items()})
                payload = (
                    raw_body
                    if raw_body is not None
                    else json.dumps(
                        {
                            "id": "chatcmpl-stub",
                            "object": "chat.completion",
                            "choices": [
                                {
                                    "index": 0,
                                    "message": {
                                        "role": "assistant",
                                        "content": stub._reply_content,
                                    },
                                    "finish_reason": "stop",
                                }
                            ],
                        }
                    ).encode("utf-8")
                )
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


def test_chat_completions_requires_auth_when_configured(authed_client):
    response = authed_client.post("/v1/chat/completions", json={"model": "any"})
    assert response.status_code == 401


def test_chat_completions_allows_auth_with_valid_token(authed_client):
    response = authed_client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer good-token"},
        json={"model": "any"},
    )
    assert response.status_code == 200


# --- request validation -----------------------------------------------------


@pytest.mark.parametrize("raw", [b"[1, 2]", b"null", b'"text"', b"7"])
def test_a_body_that_is_not_a_json_object_is_400_not_500(client, raw):
    response = client.post(
        "/v1/chat/completions", content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400


@pytest.mark.parametrize("model", [1.5, 7, ["a"], {"a": 1}, True])
def test_a_model_that_is_not_a_string_is_400_and_nothing_is_recorded(client, mesh, model):
    # A float used to reach the signed chain, which has no canonical form for
    # one, and surface as a 500.
    response = client.post("/v1/chat/completions", json={"model": model})
    assert response.status_code == 400
    assert mesh.audit_events() == []


# --- unknown agents fail closed ---------------------------------------------


def test_an_unknown_agent_is_refused_and_never_forwarded(mesh):
    with UpstreamStub() as upstream:
        app = create_app(mesh=mesh, upstream_base_url=upstream.base_url, auth_disabled=True)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/v1/chat/completions", json={"model": "m", "causalmesh_agent": "imposter"}
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "causalmesh_unknown_agent"
        assert upstream.requests == []
    assert mesh.audit_events() == []


def test_an_unknown_agent_is_refused_with_no_upstream_too(client, mesh):
    response = client.post(
        "/v1/chat/completions", json={"model": "m", "causalmesh_agent": "imposter"}
    )
    assert response.status_code == 400
    assert mesh.audit_events() == []


# --- upstream allowlist -----------------------------------------------------

ALLOWLIST_CONTRACT = """
version: 1
roles:
  - agent_id: buyer
    archetype: spender
    allow: [api.example.com]
policy:
  arm: C3
evidence:
  sign: true
"""


@pytest.fixture
def buyer_mesh(tmp_path):
    (tmp_path / "causalmesh.yaml").write_text(ALLOWLIST_CONTRACT)
    return CausalMesh(agent_id="buyer", contract=Contract.find(tmp_path), seed=b"b" * 32)


@pytest.mark.parametrize(
    "upstream",
    [
        # `#` and `?` end the authority. Text after them must not stand in for
        # the host: the connection goes to evil.example.
        "http://evil.example#.api.example.com",
        "http://evil.example?.api.example.com",
        "http://notapi.example.com",
    ],
)
def test_the_allowlist_sees_the_host_the_request_connects_to(buyer_mesh, upstream):
    app = create_app(mesh=buyer_mesh, upstream_base_url=upstream, auth_disabled=True)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/chat/completions", json={"model": "m"}
    )
    assert response.status_code == 402
    assert response.json()["error"]["rule"] == "allowlist"


@pytest.mark.parametrize(
    "upstream",
    [
        "file:///etc/passwd",
        "ftp://api.example.com/",
        "api.example.com",
        "http://",
        "http://user:pw@api.example.com",
    ],
)
def test_an_upstream_that_is_not_plain_http_is_refused_at_startup(buyer_mesh, upstream):
    # `urlopen` reads file:// as readily as http://.
    with pytest.raises(ValueError, match="upstream"):
        create_app(mesh=buyer_mesh, upstream_base_url=upstream, auth_disabled=True)


# --- upstream failure is a gateway failure ----------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.failure
def test_an_unreachable_upstream_is_502_and_the_call_is_still_recorded(mesh):
    app = create_app(
        mesh=mesh, upstream_base_url=f"http://127.0.0.1:{_free_port()}", auth_disabled=True
    )
    response = TestClient(app, raise_server_exceptions=False).post(
        "/v1/chat/completions", json={"model": "m", "causalmesh_agent": "test-agent"}
    )
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "causalmesh_upstream_error"
    # Allowed and attempted, so the evidence exists even though no reply did.
    assert len(mesh.audit_events()) == 1


@pytest.mark.parametrize("raw_body", [b"<html>not json</html>", b"[1, 2]", b'"text"'])
@pytest.mark.failure
def test_an_upstream_reply_that_is_not_a_json_object_is_502(mesh, raw_body):
    with UpstreamStub(raw_body=raw_body) as upstream:
        app = create_app(mesh=mesh, upstream_base_url=upstream.base_url, auth_disabled=True)
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions", json={"model": "m", "causalmesh_agent": "test-agent"}
        )
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "causalmesh_upstream_error"


# --- credentials are not forwarded ------------------------------------------


def test_the_upstream_key_is_sent_and_the_clients_own_token_is_not(mesh):
    # The client authenticates to CausalMesh with one secret; the upstream gets
    # a different one. Forwarding the first would hand every model provider the
    # credential that guards this server.
    with UpstreamStub() as upstream:
        app = create_app(
            mesh=mesh,
            api_tokens={"client-secret"},
            upstream_base_url=upstream.base_url,
            upstream_api_key="upstream-secret",
        )
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "test-agent"},
            headers={"Authorization": "Bearer client-secret"},
        )
        assert response.status_code == 200
        (sent,) = upstream.headers
    assert sent["authorization"] == "Bearer upstream-secret"
    assert "client-secret" not in json.dumps(sent)


def test_no_authorization_header_reaches_the_upstream_when_no_key_is_configured(mesh):
    with UpstreamStub() as upstream:
        app = create_app(
            mesh=mesh, api_tokens={"client-secret"}, upstream_base_url=upstream.base_url
        )
        TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "test-agent"},
            headers={"Authorization": "Bearer client-secret"},
        )
        (sent,) = upstream.headers
    assert "authorization" not in sent


# --- construction from a config file ----------------------------------------


def test_create_app_builds_from_a_config_path_and_still_requires_auth(tmp_path):
    (tmp_path / "causalmesh.yaml").write_text(ALLOWLIST_CONTRACT)
    app = create_app(config_path=tmp_path / "causalmesh.yaml", api_tokens={"tok"})
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/v1/tools").status_code == 401
    assert client.get("/v1/tools", headers={"Authorization": "Bearer tok"}).json() == {"tools": []}


def test_create_app_needs_a_mesh_or_a_config_path():
    with pytest.raises(ValueError, match="mesh or config_path"):
        create_app(api_tokens={"tok"})
