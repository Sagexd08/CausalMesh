"""Request ids, access logs, redaction and readiness.

What is asserted is the fact an operator relies on (the id is on the response
and in the log, no credential or body is in the log, readiness goes false when
the session cannot serve), not the exact layout of a log line.
"""

from __future__ import annotations

import io
import logging
import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from causalmesh.server import create_app
from causalmesh.server.observability import (
    REDACTED,
    RedactingFormatter,
    configure_logging,
    current_request_id,
)

pytestmark = [pytest.mark.integration]

TOKEN = "observability-token-0123456789"
UUID_HEX = re.compile(r"^[0-9a-f]{32}$")


@pytest.fixture
def authed(mesh):
    return TestClient(create_app(mesh=mesh, api_tokens={TOKEN}), raise_server_exceptions=False)


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestRequestId:
    def test_every_response_carries_a_generated_id(self, authed) -> None:
        response = authed.get("/health")
        assert UUID_HEX.match(response.headers["X-Request-ID"])

    def test_ids_differ_between_requests(self, authed) -> None:
        ids = {authed.get("/health").headers["X-Request-ID"] for _ in range(5)}
        assert len(ids) == 5

    def test_a_plain_caller_supplied_id_is_echoed(self, authed) -> None:
        response = authed.get("/health", headers={"X-Request-ID": "client-trace_1.2"})
        assert response.headers["X-Request-ID"] == "client-trace_1.2"

    @pytest.mark.parametrize(
        "hostile",
        ["a b", "x" * 65, "line\tbreak", "semi;colon", "<script>", ""],
    )
    def test_an_unsafe_supplied_id_is_replaced_not_echoed(self, authed, hostile: str) -> None:
        response = authed.get("/health", headers={"X-Request-ID": hostile})
        assert UUID_HEX.match(response.headers["X-Request-ID"])

    @pytest.mark.parametrize(
        ("method", "path", "kwargs", "status"),
        [
            ("GET", "/v1/tools", {}, 401),  # refused before the route
            ("GET", "/v1/tools", {"headers": _bearer()}, 200),
            ("GET", "/nope", {}, 404),
            (
                "POST",
                "/v1/tools/write_file/execute",
                {"headers": _bearer(), "json": {"arguments": {}}},
                422,
            ),
            (
                "POST",
                "/v1/tools/write_file/execute",
                {"headers": {**_bearer(), "Content-Length": "99999999"}, "content": b"{}"},
                413,
            ),
        ],
    )
    def test_it_is_on_error_responses_too(self, authed, method, path, kwargs, status) -> None:
        response = authed.request(method, path, **kwargs)
        assert response.status_code == status
        assert UUID_HEX.match(response.headers["X-Request-ID"])

    def test_it_is_on_an_unhandled_500_and_the_body_leaks_nothing(self, mesh) -> None:
        app = create_app(mesh=mesh, auth_disabled=True)

        @app.get("/explode")
        async def explode() -> None:
            raise RuntimeError("secret internals")

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/explode", headers={"X-Request-ID": "trace-500"})
        assert response.status_code == 500
        assert response.headers["X-Request-ID"] == "trace-500"
        assert "secret internals" not in response.text

    def test_the_id_is_not_in_the_signed_chain(self, mesh) -> None:
        client = TestClient(create_app(mesh=mesh, auth_disabled=True))
        response = client.post(
            "/v1/tools/write_file/execute",
            json={"agent_id": "test-agent", "arguments": {"path": "allowed/x"}},
            headers={"X-Request-ID": "trace-not-in-chain"},
        )
        assert response.status_code == 200
        assert "trace-not-in-chain" not in repr(mesh.audit_events())

    def test_no_id_outside_a_request(self) -> None:
        assert current_request_id() == "-"


@pytest.fixture
def served_log():
    """What `serve` would write to stderr: the real handler, pointed at a buffer."""
    stream = io.StringIO()
    undo = configure_logging(level="debug", secrets=[TOKEN])
    logging.getLogger("causalmesh").handlers[-1].setStream(stream)  # type: ignore[attr-defined]
    try:
        yield stream
    finally:
        undo()


class TestAccessLog:
    def test_a_request_is_logged_with_its_id_and_status(self, authed, served_log) -> None:
        authed.get("/v1/tools", headers={**_bearer(), "X-Request-ID": "trace-access-1"})
        lines = [ln for ln in served_log.getvalue().splitlines() if "GET /v1/tools" in ln]
        assert len(lines) == 1
        assert "[trace-access-1]" in lines[0]
        assert "200" in lines[0]

    def test_neither_the_credential_nor_the_query_nor_the_body_is_logged(
        self, authed, served_log
    ) -> None:
        authed.post(
            "/v1/tools/write_file/execute?apikey=query-secret",
            json={"agent_id": "test-agent", "arguments": {"path": "allowed/BODYMARK"}},
            headers=_bearer(),
        )
        authed.get("/v1/tools", headers=_bearer("wrong-token-0000000000"))
        text = served_log.getvalue()
        assert "execute" in text, "nothing was logged, so this test proves nothing"
        assert "401" in text
        for forbidden in (TOKEN, "wrong-token-0000000000", "query-secret", "BODYMARK", "Bearer"):
            assert forbidden not in text

    def test_a_hostile_path_cannot_forge_a_second_log_line(self, authed, served_log) -> None:
        authed.get("/x%0aFAKE-LINE%0d%1b[31m")
        text = served_log.getvalue()
        assert chr(13) not in text
        assert chr(27) not in text
        assert not any(line.startswith("FAKE-LINE") for line in text.splitlines())

    def test_the_request_id_is_in_records_logged_by_the_handler(self, mesh, served_log) -> None:
        # A refused bound-token request logs a warning from inside the route.
        bound = create_app(mesh=mesh, agent_tokens={"test-agent": TOKEN})
        TestClient(bound).post(
            "/v1/tools/write_file/execute",
            json={"agent_id": "admin-agent", "arguments": {}},
            headers={**_bearer(), "X-Request-ID": "trace-in-log"},
        )
        refused = [ln for ln in served_log.getvalue().splitlines() if "refused: a token" in ln]
        assert len(refused) == 1
        assert "[trace-in-log]" in refused[0]

    def test_an_unhandled_error_is_logged_with_its_id(self, mesh, served_log) -> None:
        app = create_app(mesh=mesh, auth_disabled=True)

        @app.get("/explode")
        async def explode() -> None:
            raise RuntimeError("boom-detail")

        TestClient(app, raise_server_exceptions=False).get(
            "/explode", headers={"X-Request-ID": "trace-boom"}
        )
        lines = [ln for ln in served_log.getvalue().splitlines() if "Unhandled exception" in ln]
        assert lines
        assert "[trace-boom]" in lines[0]


class TestRedaction:
    def _format(self, secrets, message: str, exc: BaseException | None = None) -> str:
        formatter = RedactingFormatter("%(levelname)s %(message)s", secrets=secrets)
        exc_info = None
        if exc is not None:
            try:
                raise exc
            except BaseException as caught:  # noqa: BLE001
                import sys

                exc_info = sys.exc_info()
                del caught
        record = logging.LogRecord("t", logging.ERROR, __file__, 1, message, None, exc_info)
        return formatter.format(record)

    def test_a_secret_is_removed_from_the_message(self) -> None:
        out = self._format(["hunter2-secret"], "upstream said hunter2-secret was bad")
        assert "hunter2-secret" not in out
        assert REDACTED in out

    def test_a_secret_is_removed_from_a_traceback(self) -> None:
        out = self._format(
            ["hunter2-secret"], "failed", RuntimeError("connect with key hunter2-secret")
        )
        assert "hunter2-secret" not in out
        assert "RuntimeError" in out

    def test_a_secret_that_contains_another_is_removed_whole(self) -> None:
        out = self._format(["abcd", "abcdEFGHIJ"], "x abcdEFGHIJ y")
        assert out == f"ERROR x {REDACTED} y"

    def test_a_trivially_short_secret_is_left_alone(self) -> None:
        # Redacting "ab" everywhere would destroy the log and protect nothing.
        assert "ab" in self._format(["ab"], "a table")

    def test_blank_secrets_are_ignored(self) -> None:
        assert self._format(["", ""], "unchanged") == "ERROR unchanged"

    def test_configure_logging_redacts_end_to_end_and_undoes_itself(self) -> None:
        logger = logging.getLogger("causalmesh")
        before = (list(logger.handlers), logger.level, logger.propagate)
        undo = configure_logging(level="info", secrets=["zzz-very-secret-zzz"])
        try:
            handler = logger.handlers[-1]
            stream = io.StringIO()
            handler.setStream(stream)  # type: ignore[attr-defined]
            logging.getLogger("causalmesh.server.app").warning("token zzz-very-secret-zzz leaked")
            written = stream.getvalue()
            assert "zzz-very-secret-zzz" not in written
            assert REDACTED in written
            assert "[-]" in written  # the request-id slot, outside a request
        finally:
            undo()
        assert (list(logger.handlers), logger.level, logger.propagate) == before


class TestReadiness:
    def test_a_ready_session_says_so_without_a_token(self, authed) -> None:
        response = authed.get("/readyz")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}

    def test_health_and_readiness_are_different_questions(self, mesh, monkeypatch) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={TOKEN}))
        monkeypatch.setattr(type(mesh), "agents", property(lambda self: ()))
        assert client.get("/health").status_code == 200
        response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "reasons": ["no_agent_keys"]}

    def test_an_unreadable_chain_is_not_ready(self, mesh, monkeypatch) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={TOKEN}))

        def broken(self):
            raise OSError("disk gone")

        monkeypatch.setattr(type(mesh._relay), "head_hash", property(broken))
        response = client.get("/readyz")
        assert response.status_code == 503
        assert "relay_unavailable" in response.json()["reasons"]
        assert "disk gone" not in response.text

    def test_a_missing_gate_is_not_ready(self, mesh) -> None:
        client = TestClient(create_app(mesh=mesh, api_tokens={TOKEN}))
        mesh._gate = None
        assert client.get("/readyz").json()["reasons"] == ["no_gate"]

    def test_shutdown_makes_it_not_ready_and_says_what_is_discarded(self, mesh, caplog) -> None:
        app = create_app(mesh=mesh, api_tokens={TOKEN})
        with (
            caplog.at_level(logging.INFO, logger="causalmesh.server.app"),
            TestClient(app) as client,
        ):
            assert client.get("/readyz").status_code == 200
            client.post(
                "/v1/tools/write_file/execute",
                json={"agent_id": "test-agent", "arguments": {"path": "allowed/x"}},
                headers=_bearer(),
            )
        assert app.state.shutting_down is True
        assert any("1 recorded event" in r.getMessage() for r in caplog.records)
        assert TestClient(app).get("/readyz").status_code == 503
