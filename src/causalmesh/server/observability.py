"""Request ids, access logging and secret redaction for the HTTP server.

Three small things an operator needs the moment this runs on a network:

- **A request id** on every response (`X-Request-ID`) and in every log line
  written while the request is handled, so a client's failed call and the
  server's log line about it can be joined. The id is a correlation handle
  only. It is random and time-free by construction, so it must never be
  written into the signed evidence chain (`AGENTS.md`: nothing
  non-reproducible in the signed chain), and it is not.
- **An access log line** per request: method, path, status, duration. Never
  the query string, the headers or the body. `Authorization` is a header and
  a chat request is a body, and neither has any business in a log.
- **Redaction.** Whatever the configured secrets are, a formatted log record
  (message *and* traceback) has them replaced before it is written. A tool
  handler's exception text, or an upstream library's error, can carry a
  credential that the server itself never meant to print; the operator's own
  tokens are the ones known for certain, so those are scrubbed by value.

Plain ASGI, no dependency, like `middleware.py`.
"""

from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterable
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "REQUEST_ID_HEADER",
    "SCOPE_KEY",
    "RedactingFormatter",
    "RequestIdFilter",
    "RequestIdMiddleware",
    "configure_logging",
    "current_request_id",
    "loggable",
    "request_id_for",
]

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_BYTES = REQUEST_ID_HEADER.lower().encode("latin-1")

# A caller-supplied id is honoured only if it is short and plain. Anything
# else (control characters, a log-injection attempt, a megabyte of text) is
# replaced rather than echoed into logs and response headers.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "causalmesh_request_id", default="-"
)

_access_log = logging.getLogger("causalmesh.server.access")

REDACTED = "[redacted]"

# Where the middleware leaves the id for code that runs outside it.
SCOPE_KEY = "causalmesh.request_id"

_UNPRINTABLE = re.compile(r"[^ -~]")


def loggable(text: str, limit: int = 200) -> str:
    """A client-controlled string made safe for one log line (no newlines)."""
    return _UNPRINTABLE.sub("?", text)[:limit]


def request_id_for(scope: Scope) -> str:
    """The id the middleware gave this request, or `-`."""
    return str(scope.get(SCOPE_KEY, "-"))


def current_request_id() -> str:
    """The id of the request being handled, or `-` outside one."""
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Stamps every record with the current request id as `record.request_id`."""

    def filter(self, record: logging.LogRecord) -> bool:
        # An explicit `extra={"request_id": ...}` wins: the 500 handler runs
        # outside the middleware, after the context variable has been reset.
        if not getattr(record, "request_id", None):
            record.request_id = _request_id.get()
        return True


class RedactingFormatter(logging.Formatter):
    """A formatter that removes known secrets from the whole rendered record.

    Redaction is by value, applied to the final text, so it covers the
    message, its arguments and any traceback. Secrets shorter than four
    characters are not redacted: replacing every "ab" in a log would destroy
    the log without protecting anything (and `serve` warns about weak tokens).
    """

    def __init__(self, fmt: str, secrets: Iterable[str] = ()) -> None:
        super().__init__(fmt)
        # Longest first, so a secret that contains another is removed whole.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 4}, key=len, reverse=True)

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        return text


def configure_logging(*, level: str = "info", secrets: Iterable[str] = ()) -> Callable[[], None]:
    """Send `causalmesh.*` logs to stderr with request ids and redaction.

    Returns a function that undoes it, restoring the logger's previous
    handlers, level and propagation. `serve` calls it around `uvicorn.run`, so
    the process-wide logging state is changed only while the server is up
    (and an in-process test that stubs `uvicorn.run` leaves nothing behind).
    """
    logger = logging.getLogger("causalmesh")
    previous = (logger.level, logger.propagate)
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        RedactingFormatter(
            "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s", secrets=secrets
        )
    )
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Uvicorn configures only its own loggers; without this the records would
    # also reach a root logger that may print them unredacted.
    logger.propagate = False

    def undo() -> None:
        logger.removeHandler(handler)
        logger.setLevel(previous[0])
        logger.propagate = previous[1]

    return undo


class RequestIdMiddleware:
    """Assigns each HTTP request an id, echoes it, and writes one access-log line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied = dict(scope["headers"]).get(_REQUEST_ID_BYTES)
        candidate = supplied.decode("latin-1") if supplied is not None else ""
        request_id = candidate if _SAFE_ID.fullmatch(candidate) else uuid.uuid4().hex
        scope[SCOPE_KEY] = request_id
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers: list[Any] = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != _REQUEST_ID_BYTES
                ]
                headers.append((_REQUEST_ID_BYTES, request_id.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            # `path` only: the query string, headers and body are never logged.
            _access_log.info(
                "%s %s -> %d in %.1f ms",
                scope.get("method", "-"),
                loggable(str(scope.get("path", "-"))),
                status,
                (time.perf_counter() - started) * 1000,
            )
            _request_id.reset(token)
