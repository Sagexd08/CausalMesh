"""`causalmesh serve`: an OpenAI-compatible endpoint that gates and records.

Any OpenAI-compatible client can point its base URL here; every call passes
the policy gate and enters the signed chain. Scope is deliberately narrow
(docs/FRAMEWORK-PLAN.md open question 1): allowed calls forward verbatim to
a configured upstream, or get a stub completion when none is set — this
does not proxy by default. stdlib `http.server` rather than a framework:
no new dependency for a single-route JSON endpoint.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from causalmesh.crypto.keys import KeyPair
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.policy.contract import Contract
from causalmesh.policy.gate import Gate, Verdict
from causalmesh.policy.resource import Resource, ResourceError
from causalmesh.relay import Relay

__all__ = ["ServeConfig", "run_server"]


@dataclass(slots=True)
class ServeConfig:
    """Everything `serve` needs, gathered once so the handler stays thin."""

    contract: Contract
    run_id: str
    host: str = "127.0.0.1"
    port: int = 8420
    upstream_base_url: str | None = None
    upstream_api_key: str | None = None
    default_agent: str = "agent"


class _RelayState:
    """The relay and gate, shared across request threads via one lock.

    `ThreadingHTTPServer` handles each connection on its own thread; the
    relay is already internally thread-safe for ingestion (`relay/core.py`
    serializes on its own lock), so this wrapper only needs to own
    construction, not add a second lock around calls into it.
    """

    def __init__(self, config: ServeConfig) -> None:
        self.config = config
        agent_ids = {role.agent_id for role in config.contract.roles} or {config.default_agent}
        keypairs = {agent_id: KeyPair.generate(agent_id) for agent_id in agent_ids}
        self.relay = Relay(run_id=config.run_id, keypairs=keypairs)
        self.gate = Gate(
            config.contract,
            run_id=config.run_id,
            enforcing=config.contract.arm == "C3",
        )
        self._sequence_lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    server_version = "causalmesh-serve/0.1"

    state: _RelayState

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # The chain is the record; suppress BaseHTTPRequestHandler's stderr log.
        pass

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"ok": True, "run_id": self.state.config.run_id})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._json(404, {"error": f"unsupported path {self.path!r}"})
            return

        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body: dict[str, Any] = json.loads(raw or b"{}")
        except json.JSONDecodeError as exc:
            self._json(400, {"error": f"invalid JSON body: {exc}"})
            return

        agent_id = str(body.get("causalmesh_agent") or self.state.config.default_agent)
        now_us = time.time_ns() // 1_000

        verdict = self._check_gate(agent_id=agent_id, body=body, now_us=now_us)
        self._record_event(agent_id=agent_id, body=body, verdict_allowed=verdict.allowed,
                            reason=verdict.reason, rule=verdict.rule, now_us=now_us)

        if not verdict.allowed:
            self._json(
                402 if verdict.rule in ("allowlist", "ceiling", "budget") else 403,
                {
                    "error": {
                        "message": verdict.reason,
                        "type": "causalmesh_refused",
                        "rule": verdict.rule,
                    }
                },
                extra_headers={"X-CausalMesh-Verdict": "refused"},
            )
            return

        completion = self._forward_or_stub(body)
        self._json(200, completion, extra_headers={"X-CausalMesh-Verdict": "allowed"})

    # -- gate ----------------------------------------------------------

    def _check_gate(self, *, agent_id: str, body: dict[str, Any], now_us: int) -> Verdict:
        upstream = self.state.config.upstream_base_url
        if not upstream:
            return Verdict(allowed=True, resource=Resource.endpoint("none"),
                            reason="no upstream configured; recorded only", rule="no-upstream")
        host = upstream.split("://", 1)[-1].split("/", 1)[0]
        try:
            resource = Resource.endpoint(host)
        except ResourceError as exc:
            return Verdict(allowed=False, resource=Resource.endpoint("invalid"),
                            reason=str(exc), rule="malformed")
        return self.state.gate.check(agent_id=agent_id, resource=resource, now_us=now_us)

    # -- chain -----------------------------------------------------------

    def _record_event(
        self, *, agent_id: str, body: dict[str, Any], verdict_allowed: bool, reason: str,
        rule: str, now_us: int,
    ) -> None:
        relay = self.state.relay
        identity = EventIdentity(
            experiment_id="serve",
            task_id="serve",
            run_id=self.state.config.run_id,
            agent_id=agent_id,
            arm=self.state.config.contract.arm,
        )
        event_type = EventType.INTENT if verdict_allowed else EventType.FAILURE
        relay.ingest(
            event_id=f"serve-{agent_id}-{now_us}",
            agent_id=agent_id,
            event_type=event_type,
            identity=identity,
            timestamp_us=now_us,
            payload={
                "model": body.get("model", ""),
                "allowed": verdict_allowed,
                "reason": reason,
                "rule": rule,
            },
        )

    # -- upstream ----------------------------------------------------------

    def _forward_or_stub(self, body: dict[str, Any]) -> dict[str, Any]:
        upstream = self.state.config.upstream_base_url
        if not upstream:
            return {
                "id": "causalmesh-stub",
                "object": "chat.completion",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "[causalmesh] no upstream configured; call was gated and recorded only",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "causalmesh": {"gated": True, "upstream": None},
            }
        url = upstream.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.state.config.upstream_api_key:
            headers["Authorization"] = f"Bearer {self.state.config.upstream_api_key}"
        req = urllib.request.Request(  # noqa: S310 - operator-configured upstream
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                payload: dict[str, Any] = json.loads(resp.read())
        except urllib.error.URLError as exc:
            return {
                "error": {"message": f"upstream unreachable: {exc}", "type": "causalmesh_upstream_error"}
            }
        payload.setdefault("causalmesh", {})["gated"] = True
        return payload

    # -- output ----------------------------------------------------------

    def _json(self, status: int, payload: dict[str, Any], *, extra_headers: dict[str, str] | None = None) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: _RelayState) -> None:
        self._state = state
        super().__init__(address, _Handler)

    def finish_request(self, request: Any, client_address: Any) -> None:  # noqa: D102
        handler = _Handler
        handler.state = self._state  # type: ignore[assignment]
        self.RequestHandlerClass = handler
        super().finish_request(request, client_address)


def run_server(config: ServeConfig, *, block: bool = True) -> _Server:
    """Start the server. Returns the server so callers (and tests) can stop it.

    `block=False` starts serving on a background thread and returns
    immediately — used by tests and by any caller that wants to keep control
    of the foreground.
    """
    state = _RelayState(config)
    server = _Server((config.host, config.port), state)
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
