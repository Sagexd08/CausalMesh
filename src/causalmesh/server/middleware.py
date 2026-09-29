"""A request-size limit, as plain ASGI so it needs no dependency.

Without one, `await request.json()` reads whatever a client sends into memory,
and an authenticated caller (or a runaway agent) can exhaust the process with
one request. The limit is checked twice: against `Content-Length` before any
body is read, and against the bytes actually received, because a chunked
request has no `Content-Length` to check.

When the received bytes pass the limit the app is told the client went away,
and whatever it then answers is replaced with 413. Raising into the app
instead would not do: a route that wraps `await request.json()` in a broad
`except` (this server's own chat route does) would swallow the exception and
answer 400, and a limit a handler can absorb by accident is not a limit.
"""

from __future__ import annotations

from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["BodyLimitMiddleware"]

_TOO_LARGE = b'{"detail":"request body too large"}'


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("max_bytes must be at least 1")
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > self.max_bytes
            except ValueError:
                await self._respond(send, 400, b'{"detail":"invalid Content-Length"}')
                return
            if too_large:
                await self._respond(send, 413, _TOO_LARGE)
                return

        received = 0
        exceeded = False
        answered = False

        async def limited_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def replacing_send(message: Message) -> None:
            nonlocal answered
            if not exceeded:
                await send(message)
                return
            # Past the limit, the app's own answer is discarded for ours.
            if not answered:
                answered = True
                await self._respond(send, 413, _TOO_LARGE)

        try:
            await self.app(scope, limited_receive, replacing_send)
        except Exception:
            if not (exceeded and not answered):
                raise
        if exceeded and not answered:
            await self._respond(send, 413, _TOO_LARGE)

    @staticmethod
    async def _respond(send: Send, status: int, body: bytes) -> None:
        headers: list[Any] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"connection", b"close"),
        ]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
