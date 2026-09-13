"""A real HTTP server speaking the chat-completions protocols.

Not a mock. It binds a socket, accepts connections, parses JSON bodies and
returns JSON responses, so the adapters are exercised over genuine network
I/O — real serialization, real status codes, real error paths.

Why this rather than patching `urllib`: a patched transport tests that the
adapter calls a function. This tests that the adapter speaks the protocol.
The difference showed up immediately — Anthropic hoists the system prompt
out of the message list, and a mocked transport would happily accept the
wrong shape while a real endpoint rejects it.

The server is scriptable: each agent gets a queue of replies, so a test can
drive an exact sequence of tool calls deterministically. That keeps the
adapter tests reproducible while still exercising the real wire path — the
nondeterminism a live model would add is the thing under study elsewhere,
not something these tests should inherit.
"""

from __future__ import annotations

import json
import threading
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

__all__ = ["FakeModelServer"]


class FakeModelServer:
    """An OpenAI- and Anthropic-compatible endpoint on a real socket."""

    def __init__(self) -> None:
        self._replies: dict[str, deque[str]] = defaultdict(deque)
        self._default_reply = json.dumps({"tool": None, "done": True, "reasoning": "idle"})
        self.requests: list[dict[str, Any]] = []
        self._status_override: int | None = None
        self._body_override: str | None = None
        self._lock = threading.Lock()
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # -- scripting --------------------------------------------------------

    def queue_reply(self, agent_id: str, reply: str) -> None:
        """Queue one raw reply body for the named agent.

        Keyed by agent because a coordination test needs two agents taking
        different actions in the same run, and the only thing distinguishing
        their requests is the system prompt naming them.
        """
        with self._lock:
            self._replies[agent_id].append(reply)

    def queue_action(self, agent_id: str, **action: Any) -> None:
        """Queue a well-formed action object."""
        self.queue_reply(agent_id, json.dumps(action))

    def fail_next(self, status: int, body: str = '{"error": "injected"}') -> None:
        """Make the next request fail with a status code.

        Fault injection at the transport layer (§22), so the adapter's
        error handling is tested against a real HTTP error rather than a
        raised exception.
        """
        with self._lock:
            self._status_override = status
            self._body_override = body

    # -- lifecycle --------------------------------------------------------

    def __enter__(self) -> FakeModelServer:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                """Silence the default stderr access log."""

            def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    body = {"_unparseable": raw.decode("utf-8", "replace")}

                anthropic = self.path.rstrip("/").endswith("messages")
                with server._lock:
                    server.requests.append(
                        {"body": body, "headers": dict(self.headers), "path": self.path}
                    )
                    status = server._status_override
                    override = server._body_override
                    server._status_override = None
                    server._body_override = None

                if status is not None:
                    payload = (override or "{}").encode("utf-8")
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return

                text = server._next_reply(body, anthropic=anthropic)
                response = (
                    server._anthropic_envelope(text, body)
                    if anthropic
                    else server._openai_envelope(text, body)
                )
                payload = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def base_url(self) -> str:
        assert self._server is not None, "server is not running"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    # -- internals --------------------------------------------------------

    def _next_reply(self, body: dict[str, Any], *, anthropic: bool) -> str:
        """Pick the queued reply for whichever agent sent this request."""
        system = body.get("system", "") if anthropic else ""
        if not system:
            system = "\n".join(
                m.get("content", "")
                for m in body.get("messages", [])
                if m.get("role") == "system"
            )
        with self._lock:
            for agent_id, queue in self._replies.items():
                if f"You are {agent_id}," in system and queue:
                    return queue.popleft()
        return self._default_reply

    @staticmethod
    def _openai_envelope(text: str, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "choices": [
                {"finish_reason": "stop", "index": 0, "message": {"content": text, "role": "assistant"}}
            ],
            "id": "chatcmpl-fake",
            "model": request.get("model", "fake-model"),
            "object": "chat.completion",
            "usage": {
                "completion_tokens": max(1, len(text) // 4),
                "prompt_tokens": 100,
                "total_tokens": 100 + max(1, len(text) // 4),
            },
        }

    @staticmethod
    def _anthropic_envelope(text: str, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "content": [{"text": text, "type": "text"}],
            "id": "msg_fake",
            "model": request.get("model", "fake-model"),
            "role": "assistant",
            "stop_reason": "end_turn",
            "type": "message",
            "usage": {"input_tokens": 100, "output_tokens": max(1, len(text) // 4)},
        }
