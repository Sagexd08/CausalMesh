"""Who a request is, and what one request may cost.

Two questions the server used to answer loosely.

**Identity.** The bearer token authenticated the *client*; the agent was
whatever the request said it was. A token can now be bound to one agent, and
then the server takes the agent from the token and refuses a request that names
another. An unbound token is still the operator's, and still asserts.

**Cost.** One request could hold the event loop for as long as a handler or the
upstream took, read an unbounded body into memory, or reach the docs and schema
without a token. Each of those is bounded below, and the tests say how.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import threading
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from causalmesh import CausalMesh, Tool
from causalmesh.cli.main import app as cli
from causalmesh.crypto.keys import PublicKeyRing
from causalmesh.policy.contract import Contract
from causalmesh.server import create_app
from causalmesh.server.auth import SlidingWindowLimiter
from causalmesh.verifier import verify_chain

pytestmark = pytest.mark.integration

CONTRACT = """
version: 1
roles:
  - agent_id: alice
    archetype: writer
    owns: [alice/]
  - agent_id: bob
    archetype: writer
    owns: [bob/]
policy:
  arm: C3
evidence:
  sign: true
"""

ALICE = "alice-token-0000000000000000"
BOB = "bob-token-000000000000000000"
SHARED = "operator-token-000000000000"


def _mesh(tmp_path: Path) -> CausalMesh:
    (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
    mesh = CausalMesh(
        agent_id="alice", contract=Contract.find(tmp_path), seed=b"identity-0000000000000000000000"
    )
    mesh.register_tool(
        Tool(name="echo", handler=lambda path: f"echo:{path}", resource_args=["path"])
    )
    return mesh


@pytest.fixture
def mesh(tmp_path: Path) -> CausalMesh:
    return _mesh(tmp_path)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _execute(client: TestClient, token: str, agent: str, path: str = "alice/x") -> Any:
    return client.post(
        "/v1/tools/echo/execute",
        json={"agent_id": agent, "arguments": {"path": path}},
        headers=_auth(token),
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestABoundTokenFixesTheAgent:
    @pytest.fixture
    def client(self, mesh: CausalMesh) -> TestClient:
        app = create_app(mesh=mesh, agent_tokens={"alice": ALICE, "bob": BOB})
        return TestClient(app, raise_server_exceptions=False)

    def test_a_token_acts_as_its_own_agent(self, client: TestClient, mesh: CausalMesh) -> None:
        assert _execute(client, ALICE, "alice").status_code == 200
        assert _execute(client, BOB, "bob", "bob/y").status_code == 200
        assert [e["event"]["identity"]["agent_id"] for e in mesh.audit_events()] == ["alice", "bob"]

    def test_a_token_cannot_act_as_another_agent(
        self, client: TestClient, mesh: CausalMesh
    ) -> None:
        # bob's token, alice's name: this is the impersonation a shared token allowed.
        response = _execute(client, BOB, "alice", "alice/x")
        assert response.status_code == 403
        assert response.json() == {"detail": "this token is bound to a different agent"}
        assert mesh.audit_events() == [], "the refused request must not have run or been recorded"

    def test_a_refusal_does_not_say_which_agents_exist(self, client: TestClient) -> None:
        response = _execute(client, ALICE, "mallory")
        assert response.status_code == 403
        assert "bob" not in response.text

    def test_an_unknown_token_is_401_whatever_agent_it_names(self, client: TestClient) -> None:
        assert _execute(client, "guess", "alice").status_code == 401

    def test_the_token_can_list_tools(self, client: TestClient) -> None:
        assert client.get("/v1/tools", headers=_auth(ALICE)).status_code == 200

    def test_chat_takes_the_agent_from_the_token_when_the_body_names_none(
        self, client: TestClient, mesh: CausalMesh
    ) -> None:
        response = client.post("/v1/chat/completions", json={"model": "m"}, headers=_auth(BOB))
        assert response.status_code == 200
        event = mesh.audit_events()[-1]["event"]
        assert event["identity"]["agent_id"] == "bob"
        assert event["payload"]["identity_source"] == "token-bound"

    def test_chat_refuses_a_body_that_names_a_different_agent(
        self, client: TestClient, mesh: CausalMesh
    ) -> None:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "alice"},
            headers=_auth(BOB),
        )
        assert response.status_code == 403
        assert mesh.audit_events() == []

    def test_chat_accepts_a_body_that_names_the_same_agent(self, client: TestClient) -> None:
        response = client.post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "bob"},
            headers=_auth(BOB),
        )
        assert response.status_code == 200


class TestAnUnboundTokenAssertsAndSaysSo:
    def test_it_may_name_any_agent_that_has_a_key(self, mesh: CausalMesh) -> None:
        client = TestClient(
            create_app(mesh=mesh, api_tokens={SHARED}), raise_server_exceptions=False
        )
        assert _execute(client, SHARED, "alice").status_code == 200
        assert _execute(client, SHARED, "bob", "bob/y").status_code == 200

    def test_the_chain_records_that_the_agent_was_only_asserted(self, mesh: CausalMesh) -> None:
        client = TestClient(
            create_app(mesh=mesh, api_tokens={SHARED}), raise_server_exceptions=False
        )
        client.post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "bob"},
            headers=_auth(SHARED),
        )
        assert mesh.audit_events()[-1]["event"]["payload"]["identity_source"] == "asserted"

    def test_bound_and_unbound_tokens_can_coexist(self, mesh: CausalMesh) -> None:
        app = create_app(mesh=mesh, api_tokens={SHARED}, agent_tokens={"bob": BOB})
        client = TestClient(app, raise_server_exceptions=False)
        assert _execute(client, SHARED, "alice").status_code == 200
        assert _execute(client, BOB, "alice").status_code == 403


class TestTokenConfigurationIsRefusedWhenItWouldMeanLess:
    def test_a_token_for_an_agent_the_session_has_no_key_for(self, mesh: CausalMesh) -> None:
        with pytest.raises(ValueError, match="no key for.*mallory"):
            create_app(mesh=mesh, agent_tokens={"mallory": ALICE})

    def test_one_token_for_two_agents(self, mesh: CausalMesh) -> None:
        with pytest.raises(ValueError, match="two agents"):
            create_app(mesh=mesh, agent_tokens={"alice": ALICE, "bob": ALICE})

    def test_a_token_that_is_both_bound_and_unbound(self, mesh: CausalMesh) -> None:
        with pytest.raises(ValueError, match="also configured as unbound"):
            create_app(mesh=mesh, api_tokens={ALICE}, agent_tokens={"alice": ALICE})

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_a_blank_agent_token(self, mesh: CausalMesh, blank: str) -> None:
        with pytest.raises(ValueError, match="non-blank"):
            create_app(mesh=mesh, agent_tokens={"alice": blank})

    def test_turning_auth_off_while_giving_tokens_is_a_contradiction_not_a_default(
        self, mesh: CausalMesh
    ) -> None:
        # It used to resolve in favour of no auth, silently.
        with pytest.raises(ValueError, match="contradicts"):
            create_app(mesh=mesh, api_tokens={SHARED}, auth_disabled=True)
        with pytest.raises(ValueError, match="contradicts"):
            create_app(mesh=mesh, agent_tokens={"alice": ALICE}, auth_disabled=True)

    def test_agent_tokens_alone_satisfy_the_authentication_requirement(
        self, mesh: CausalMesh
    ) -> None:
        app = create_app(mesh=mesh, agent_tokens={"alice": ALICE})
        assert TestClient(app).get("/v1/tools", headers=_auth(ALICE)).status_code == 200


# ---------------------------------------------------------------------------
# CLI wiring for bound tokens
# ---------------------------------------------------------------------------


class TestServeAgentTokenOption:
    @staticmethod
    def _run(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        args: list[str],
        env: dict[str, str] | None = None,
    ) -> tuple[Any, list[Any]]:
        uvicorn = pytest.importorskip("uvicorn")
        apps: list[Any] = []
        monkeypatch.setattr(uvicorn, "run", lambda application, **_: apps.append(application))
        (tmp_path / "causalmesh.yaml").write_text(CONTRACT, encoding="utf-8")
        result = CliRunner().invoke(cli, ["serve", "--root", str(tmp_path), *args], env=env)
        return result, apps

    def test_a_bound_token_is_enforced(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = self._run(tmp_path, monkeypatch, ["--agent-token", f"bob={BOB}"])
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools").status_code == 401
        assert client.get("/v1/tools", headers=_auth(BOB)).status_code == 200
        bad = client.post(
            "/v1/chat/completions",
            json={"model": "m", "causalmesh_agent": "alice"},
            headers=_auth(BOB),
        )
        assert bad.status_code == 403

    def test_dev_with_an_agent_token_still_enforces_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = self._run(tmp_path, monkeypatch, ["--dev", "--agent-token", f"bob={BOB}"])
        assert result.exit_code == 0, result.output
        assert TestClient(apps[0]).get("/v1/tools").status_code == 401

    def test_the_environment_variable_carries_several_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = self._run(
            tmp_path, monkeypatch, [], env={"CAUSALMESH_AGENT_TOKENS": f"alice={ALICE} bob={BOB}"}
        )
        assert result.exit_code == 0, result.output
        client = TestClient(apps[0], raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(ALICE)).status_code == 200
        assert client.get("/v1/tools", headers=_auth(BOB)).status_code == 200

    @pytest.mark.parametrize("pair", ["nope", "=tok", "alice=", "alice=   ", " =x"])
    def test_a_malformed_pair_is_a_usage_error_and_nothing_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pair: str
    ) -> None:
        result, apps = self._run(tmp_path, monkeypatch, ["--agent-token", pair])
        assert apps == []
        assert result.exit_code == 2
        assert "AGENT=TOKEN" in result.output

    def test_an_agent_the_contract_does_not_declare_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = self._run(tmp_path, monkeypatch, ["--agent-token", f"mallory={ALICE}"])
        assert apps == []
        assert result.exit_code == 2
        assert "mallory" in result.output

    def test_the_same_agent_twice_is_a_usage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, apps = self._run(
            tmp_path, monkeypatch, ["--agent-token", f"bob={BOB}", "--agent-token", f"bob={ALICE}"]
        )
        assert apps == [] and result.exit_code == 2

    def test_a_short_token_is_reported_as_guessable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, _ = self._run(tmp_path, monkeypatch, ["--api-token", "short"])
        assert result.exit_code == 0
        assert "shorter than 16" in result.output

    def test_a_long_token_is_not(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        result, _ = self._run(tmp_path, monkeypatch, ["--api-token", SHARED])
        assert "shorter than 16" not in result.output


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDocsAndSchemaAreNotPublic:
    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_they_are_absent_when_auth_is_on_even_with_a_valid_token(
        self, mesh: CausalMesh, path: str
    ) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={SHARED}))
        assert client.get(path).status_code == 404
        assert client.get(path, headers=_auth(SHARED)).status_code == 404

    @pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
    def test_they_are_served_in_dev_mode(self, mesh: CausalMesh, path: str) -> None:
        assert TestClient(create_app(mesh=mesh, auth_disabled=True)).get(path).status_code == 200

    def test_the_reported_version_is_the_packages(self, mesh: CausalMesh) -> None:
        from causalmesh import __version__

        schema = TestClient(create_app(mesh=mesh, auth_disabled=True)).get("/openapi.json").json()
        assert schema["info"]["version"] == __version__


# ---------------------------------------------------------------------------
# Request size
# ---------------------------------------------------------------------------


class TestBodyLimit:
    @pytest.fixture
    def client(self, mesh: CausalMesh) -> TestClient:
        app = create_app(mesh=mesh, api_tokens={SHARED}, max_body_bytes=200)
        return TestClient(app, raise_server_exceptions=False)

    def test_a_body_over_the_limit_is_413_before_anything_runs(
        self, client: TestClient, mesh: CausalMesh
    ) -> None:
        big = {"agent_id": "alice", "arguments": {"path": "alice/" + "x" * 500}}
        response = client.post("/v1/tools/echo/execute", json=big, headers=_auth(SHARED))
        assert response.status_code == 413
        assert response.json() == {"detail": "request body too large"}
        assert mesh.audit_events() == []

    def test_the_same_holds_for_chat(self, client: TestClient) -> None:
        response = client.post(
            "/v1/chat/completions", json={"model": "m", "pad": "x" * 500}, headers=_auth(SHARED)
        )
        assert response.status_code == 413

    def test_a_body_that_is_chunked_and_has_no_length_to_check_is_still_limited(
        self, client: TestClient
    ) -> None:
        def chunks() -> Any:
            for _ in range(10):
                yield b"x" * 50

        response = client.post(
            "/v1/chat/completions",
            content=chunks(),
            headers={**_auth(SHARED), "Content-Type": "application/json"},
        )
        assert response.status_code == 413

    def test_a_body_under_the_limit_is_untouched(self, client: TestClient) -> None:
        response = client.post(
            "/v1/tools/echo/execute",
            json={"agent_id": "alice", "arguments": {"path": "alice/x"}},
            headers=_auth(SHARED),
        )
        assert response.status_code == 200

    def test_the_limit_is_checked_before_authentication_reads_anything(
        self, client: TestClient
    ) -> None:
        # An unauthenticated caller cannot make the server buffer a large body.
        response = client.post("/v1/chat/completions", json={"pad": "x" * 500})
        assert response.status_code == 413

    def test_a_nonsensical_limit_is_refused(self, mesh: CausalMesh) -> None:
        with pytest.raises(ValueError, match="max_body_bytes"):
            create_app(mesh=mesh, api_tokens={SHARED}, max_body_bytes=0)


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


class TestRateLimit:
    def test_the_window_slides(self) -> None:
        limiter = SlidingWindowLimiter(2, window_s=10.0)
        assert limiter.retry_after("k", now=0.0) is None
        assert limiter.retry_after("k", now=1.0) is None
        wait = limiter.retry_after("k", now=2.0)
        assert wait is not None and 7.9 < wait <= 8.0
        assert limiter.retry_after("other", now=2.0) is None, "keys are independent"
        assert limiter.retry_after("k", now=10.1) is None, "the first hit has aged out"

    def test_a_limit_below_one_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least 1"):
            SlidingWindowLimiter(0)

    def test_a_credential_over_its_limit_gets_429_with_retry_after(self, mesh: CausalMesh) -> None:
        app = create_app(mesh=mesh, api_tokens={SHARED}, rate_limit_per_minute=3)
        client = TestClient(app, raise_server_exceptions=False)
        assert [client.get("/v1/tools", headers=_auth(SHARED)).status_code for _ in range(3)] == [
            200
        ] * 3
        limited = client.get("/v1/tools", headers=_auth(SHARED))
        assert limited.status_code == 429
        assert int(limited.headers["Retry-After"]) >= 1

    def test_each_credential_has_its_own_allowance(self, mesh: CausalMesh) -> None:
        app = create_app(
            mesh=mesh, agent_tokens={"alice": ALICE, "bob": BOB}, rate_limit_per_minute=1
        )
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/v1/tools", headers=_auth(ALICE)).status_code == 200
        assert client.get("/v1/tools", headers=_auth(ALICE)).status_code == 429
        assert client.get("/v1/tools", headers=_auth(BOB)).status_code == 200

    def test_a_wrong_token_is_401_and_never_spends_anyones_allowance(
        self, mesh: CausalMesh
    ) -> None:
        # A throttle keyed on failures would let anyone lock out a real user
        # behind the same address, so failures are not throttled here at all.
        app = create_app(mesh=mesh, api_tokens={SHARED}, rate_limit_per_minute=1)
        client = TestClient(app, raise_server_exceptions=False)
        for _ in range(5):
            assert client.get("/v1/tools", headers=_auth("wrong")).status_code == 401
        assert client.get("/v1/tools", headers=_auth(SHARED)).status_code == 200

    def test_there_is_no_limit_unless_one_is_asked_for(self, mesh: CausalMesh) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={SHARED}))
        assert all(
            client.get("/v1/tools", headers=_auth(SHARED)).status_code == 200 for _ in range(50)
        )


# ---------------------------------------------------------------------------
# The event loop, and the one chain
# ---------------------------------------------------------------------------


def _read_request(connection: socket.socket) -> bytes:
    """Read one whole HTTP request, headers and body.

    A stub that answers after reading only part of it and then closes makes
    Windows reset the connection, and the client sees an error instead of the
    response the test is about.
    """
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = connection.recv(65536)
        if not chunk:
            return data
        data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    length = 0
    for line in head.split(b"\r\n")[1:]:
        name, _, value = line.partition(b":")
        if name.strip().lower() == b"content-length":
            length = int(value)
    while len(body) < length:
        chunk = connection.recv(65536)
        if not chunk:
            break
        body += chunk
    return data


def _async_client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class TestASlowHandlerDoesNotStallTheServer:
    async def test_health_answers_while_a_sync_handler_is_still_running(
        self, mesh: CausalMesh
    ) -> None:
        # If the handler ran on the event loop, /health could not be answered
        # until it returned, and this would time out rather than pass slowly.
        release = threading.Event()
        started = threading.Event()

        def slow(path: str) -> str:
            started.set()
            release.wait(timeout=10)
            return "done"

        mesh.register_tool(Tool(name="slow", handler=slow, resource_args=["path"]))
        async with _async_client(create_app(mesh=mesh, api_tokens={SHARED})) as client:
            call = asyncio.create_task(
                client.post(
                    "/v1/tools/slow/execute",
                    json={"agent_id": "alice", "arguments": {"path": "alice/x"}},
                    headers=_auth(SHARED),
                )
            )
            while not started.is_set():
                await asyncio.sleep(0.01)
            health = await asyncio.wait_for(client.get("/health"), timeout=3)
            assert health.status_code == 200
            assert not call.done(), "the handler should still be running"
            release.set()
            response = await asyncio.wait_for(call, timeout=5)
        assert response.status_code == 200
        assert response.json()["value"] == "done"

    async def test_health_answers_while_the_upstream_is_still_thinking(
        self, mesh: CausalMesh
    ) -> None:
        release = threading.Event()
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        def upstream() -> None:
            connection, _ = listener.accept()
            _read_request(connection)
            release.wait(timeout=10)
            body = b'{"id":"x","choices":[]}'
            connection.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\nConnection: close\r\n\r\n"
                + body
            )
            connection.shutdown(socket.SHUT_WR)
            connection.close()

        threading.Thread(target=upstream, daemon=True).start()
        app = create_app(
            mesh=mesh, api_tokens={SHARED}, upstream_base_url=f"http://127.0.0.1:{port}"
        )
        try:
            async with _async_client(app) as client:
                call = asyncio.create_task(
                    client.post("/v1/chat/completions", json={"model": "m"}, headers=_auth(SHARED))
                )
                await asyncio.sleep(0.3)
                health = await asyncio.wait_for(client.get("/health"), timeout=3)
                assert health.status_code == 200
                assert not call.done()
                release.set()
                response = await asyncio.wait_for(call, timeout=5)
            assert response.status_code == 200
        finally:
            release.set()
            listener.close()


class TestConcurrentCallsShareOneChain:
    async def test_calls_never_overlap_and_the_chain_verifies(self, mesh: CausalMesh) -> None:
        lock = threading.Lock()
        running = 0
        peak = 0

        def busy(path: str) -> str:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            threading.Event().wait(0.01)
            with lock:
                running -= 1
            return path

        async def abusy(path: str) -> str:
            return busy(path)

        mesh.register_tool(Tool(name="busy", handler=busy, resource_args=["path"]))
        mesh.register_tool(Tool(name="abusy", handler=abusy, resource_args=["path"]))
        async with _async_client(create_app(mesh=mesh, api_tokens={SHARED})) as client:
            responses = await asyncio.gather(
                *(
                    client.post(
                        f"/v1/tools/{'busy' if i % 2 else 'abusy'}/execute",
                        json={"agent_id": "alice", "arguments": {"path": f"alice/{i}"}},
                        headers=_auth(SHARED),
                    )
                    for i in range(30)
                ),
                *(
                    client.post("/v1/chat/completions", json={"model": "m"}, headers=_auth(SHARED))
                    for _ in range(10)
                ),
            )
        assert [r.status_code for r in responses] == [200] * 40
        assert peak == 1, "two tool calls ran at once on one session"
        events = mesh.audit_events()
        assert len(events) == 40
        assert len({e["event"]["event_id"] for e in events}) == 40
        ring = PublicKeyRing.from_keypairs(mesh._relay._keypairs)
        assert verify_chain(events, ring).valid


# ---------------------------------------------------------------------------
# What a response is allowed to say
# ---------------------------------------------------------------------------


class TestResponses:
    def _client(self, mesh: CausalMesh) -> TestClient:
        return TestClient(create_app(mesh=mesh, api_tokens={SHARED}), raise_server_exceptions=False)

    def _register(self, mesh: CausalMesh, name: str, handler: Any) -> None:
        mesh.register_tool(Tool(name=name, handler=handler, resource_args=["path"]))

    def _call(self, client: TestClient, name: str) -> Any:
        return client.post(
            f"/v1/tools/{name}/execute",
            json={"agent_id": "alice", "arguments": {"path": "alice/x"}},
            headers=_auth(SHARED),
        )

    def test_the_handlers_return_value_reaches_the_client(self, mesh: CausalMesh) -> None:
        self._register(mesh, "data", lambda path: {"path": path, "n": [1, 2.5, None, True]})
        body = self._call(self._client(mesh), "data").json()
        assert body["value"] == {"path": "alice/x", "n": [1, 2.5, None, True]}
        assert body["value_omitted"] is None

    def test_a_tool_that_returns_nothing_has_no_value_and_no_complaint(
        self, mesh: CausalMesh
    ) -> None:
        self._register(mesh, "nothing", lambda path: None)
        body = self._call(self._client(mesh), "nothing").json()
        assert body["value"] is None and body["value_omitted"] is None

    def test_an_object_is_not_serialized_from_its_attributes(self, mesh: CausalMesh) -> None:
        class Client:
            def __init__(self) -> None:
                self.api_key = "sk-do-not-send"

        self._register(mesh, "leaky", lambda path: Client())
        response = self._call(self._client(mesh), "leaky")
        assert response.status_code == 200, "the tool ran; the response must not pretend it did not"
        assert "sk-do-not-send" not in response.text
        body = response.json()
        assert body["executed"] is True and body["value"] is None
        assert "not plain JSON" in body["value_omitted"]

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), b"bytes", {1, 2}, object()])
    def test_a_value_that_is_not_plain_json_is_omitted_not_a_500(
        self, mesh: CausalMesh, value: object
    ) -> None:
        self._register(mesh, "odd", lambda path: value)
        response = self._call(self._client(mesh), "odd")
        assert response.status_code == 200
        assert response.json()["value_omitted"]

    def test_an_async_handlers_value_is_returned_too(self, mesh: CausalMesh) -> None:
        async def handler(path: str) -> str:
            return "async:" + path

        self._register(mesh, "adata", handler)
        assert self._call(self._client(mesh), "adata").json()["value"] == "async:alice/x"

    def test_a_denied_call_returns_no_value(self, mesh: CausalMesh) -> None:
        self._register(mesh, "data", lambda path: "secret")
        response = self._client(mesh).post(
            "/v1/tools/data/execute",
            json={"agent_id": "alice", "arguments": {"path": "bob/x"}},
            headers=_auth(SHARED),
        )
        assert response.status_code == 403
        assert "secret" not in response.text

    @pytest.mark.failure
    def test_the_text_of_a_handlers_exception_stays_on_the_server(
        self, mesh: CausalMesh, caplog: pytest.LogCaptureFixture
    ) -> None:
        def boom(path: str) -> None:
            raise RuntimeError("connect to db://admin:hunter2@internal failed")

        self._register(mesh, "boom", boom)
        with caplog.at_level(logging.WARNING):
            response = self._call(self._client(mesh), "boom")
        body = response.json()
        assert response.status_code == 200 and body["failed"] is True
        assert body["reason"] == "the tool raised RuntimeError"
        assert "hunter2" not in response.text
        assert "hunter2" in caplog.text, "the operator still gets the detail"

    def test_the_record_keeps_the_full_reason_for_the_audit(self, mesh: CausalMesh) -> None:
        def boom(path: str) -> None:
            raise RuntimeError("detail for the audit")

        self._register(mesh, "boom", boom)
        self._call(self._client(mesh), "boom")
        assert "detail for the audit" in json.dumps(mesh.audit_events()[-1]["event"]["payload"])


class TestLogsNeverCarryACredential:
    def test_a_refused_request_is_logged_without_the_token(
        self, mesh: CausalMesh, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={SHARED}))
        guess = "guessed-token-should-not-appear"
        with caplog.at_level(logging.WARNING):
            assert client.get("/v1/tools", headers=_auth(guess)).status_code == 401
            assert client.get("/v1/tools").status_code == 401
        assert "authentication refused" in caplog.text
        assert "/v1/tools" in caplog.text
        assert guess not in caplog.text
        assert SHARED not in caplog.text

    def test_a_successful_request_logs_no_credential(
        self, mesh: CausalMesh, caplog: pytest.LogCaptureFixture
    ) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={SHARED}))
        with caplog.at_level(logging.DEBUG):
            client.get("/v1/tools", headers=_auth(SHARED))
        assert SHARED not in caplog.text


class TestTheUpstreamIsNotFollowedElsewhere:
    def _serve(
        self, status: int, headers: dict[str, str], seen: list[bytes]
    ) -> tuple[int, socket.socket]:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(2)

        def run() -> None:
            while True:
                try:
                    connection, _ = listener.accept()
                except OSError:
                    return
                seen.append(_read_request(connection))
                head = f"HTTP/1.1 {status} X\r\nContent-Length: 2\r\nConnection: close\r\n"
                head += "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n{}"
                connection.sendall(head.encode())
                connection.shutdown(socket.SHUT_WR)
                connection.close()

        threading.Thread(target=run, daemon=True).start()
        return listener.getsockname()[1], listener

    @pytest.mark.failure
    def test_a_redirect_is_not_followed_and_the_key_goes_nowhere_else(
        self, mesh: CausalMesh
    ) -> None:
        elsewhere: list[bytes] = []
        first: list[bytes] = []
        other_port, other = self._serve(200, {}, elsewhere)
        port, listener = self._serve(302, {"Location": f"http://127.0.0.1:{other_port}/"}, first)
        try:
            app = create_app(
                mesh=mesh,
                api_tokens={SHARED},
                upstream_base_url=f"http://127.0.0.1:{port}",
                upstream_api_key="upstream-secret",
            )
            response = TestClient(app, raise_server_exceptions=False).post(
                "/v1/chat/completions", json={"model": "m"}, headers=_auth(SHARED)
            )
        finally:
            listener.close()
            other.close()
        assert response.status_code == 502
        assert "302" in response.json()["error"]["message"]
        assert len(first) == 1
        assert elsewhere == [], "the redirect was followed, and the upstream key went with it"

    @pytest.mark.failure
    def test_the_error_does_not_name_the_upstream_host(self, mesh: CausalMesh) -> None:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            dead = probe.getsockname()[1]
        app = create_app(
            mesh=mesh, api_tokens={SHARED}, upstream_base_url=f"http://127.0.0.1:{dead}"
        )
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions", json={"model": "m"}, headers=_auth(SHARED)
        )
        assert response.status_code == 502
        assert str(dead) not in response.text
        assert "127.0.0.1" not in response.text


class TestEveryAllowedChatCallIsRecordedOrNotForwarded:
    def test_calls_in_one_clock_tick_all_get_their_own_record(
        self, mesh: CausalMesh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The event id used to be `serve-<agent>-<microseconds>`. On a coarse clock
        # (Windows) two requests share a tick, the relay refuses the duplicate id,
        # and the second call was forwarded with no record. Freezing the clock
        # makes that certain rather than likely.
        import time as real_time

        monkeypatch.setattr(real_time, "time_ns", lambda: 1_700_000_000_000_000_000)
        client = TestClient(
            create_app(mesh=mesh, api_tokens={SHARED}), raise_server_exceptions=False
        )
        for _ in range(12):
            assert (
                client.post(
                    "/v1/chat/completions", json={"model": "m"}, headers=_auth(SHARED)
                ).status_code
                == 200
            )
        events = mesh.audit_events()
        assert len(events) == 12
        assert len({e["event"]["event_id"] for e in events}) == 12

    @pytest.mark.failure
    def test_an_allowed_call_the_relay_would_not_accept_is_not_forwarded(
        self, mesh: CausalMesh, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        forwarded: list[object] = []
        monkeypatch.setattr(
            "causalmesh.server.app._forward", lambda *a, **k: forwarded.append(a) or {"id": "x"}
        )
        monkeypatch.setattr(
            mesh._relay, "ingest", lambda **_: SimpleNamespace(accepted=False, reason="chain full")
        )
        app = create_app(
            mesh=mesh, api_tokens={SHARED}, upstream_base_url="http://upstream.example"
        )
        response = TestClient(app, raise_server_exceptions=False).post(
            "/v1/chat/completions", json={"model": "m"}, headers=_auth(SHARED)
        )
        assert response.status_code == 503
        assert response.json()["error"]["type"] == "causalmesh_audit_unavailable"
        assert "chain full" not in response.text
        assert forwarded == [], "an action with no evidence was sent upstream"
