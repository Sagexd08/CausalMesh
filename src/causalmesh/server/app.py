from __future__ import annotations

import asyncio
import functools
import inspect
import itertools
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from causalmesh import __version__
from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.policy.resource import Resource, ResourceError
from causalmesh.sdk.errors import MissingResourceError, ToolNotFoundError, UnknownAgentError
from causalmesh.sdk.mesh import CausalMesh

from .auth import Principal, make_auth_checker
from .errors import register_error_handlers
from .middleware import BodyLimitMiddleware
from .models import ExecuteRequest, ExecuteResponse, ToolListResponse, ToolMeta
from .observability import RequestIdMiddleware

log = logging.getLogger(__name__)

# One megabyte covers any chat request a gate-and-record proxy should carry and
# any tool arguments an agent should send; a larger limit is the operator's call.
DEFAULT_MAX_BODY_BYTES = 1_048_576


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse to follow a redirect from the upstream.

    `urllib` re-sends the request headers to the redirect target, which would
    hand the upstream API key to whatever host the redirect names, and the
    allowlist only ever saw the host the operator configured.
    """

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_UPSTREAM = urllib.request.build_opener(_NoRedirect)


def _upstream_host(url: str) -> str:
    """The `host[:port]` an upstream URL connects to, refusing non-HTTP schemes.

    `urlopen` would read a `file://` URL as readily as an HTTP one, so the
    scheme is checked once at startup, as `HttpTransport` checks it. The host
    comes from the parsed URL rather than a string split: a `#` or `?` in the
    URL must not let text after it stand in for the host the allowlist sees.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError(
            f"refusing upstream URL with scheme {parts.scheme or '(none)'!r}: "
            "only http and https are permitted"
        )
    if not parts.hostname or parts.username is not None:
        raise ValueError("upstream URL must name a host and carry no credentials")
    return parts.hostname if parts.port is None else f"{parts.hostname}:{parts.port}"


def _forward(url: str, headers: dict[str, str], data: bytes) -> dict[str, Any]:
    """POST to the upstream and return its JSON object. Blocking: run it in a thread."""
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with _UPSTREAM.open(request, timeout=60) as response:  # nosec B310
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise ValueError("upstream did not return a JSON object")
    return payload


def _identity_source(principal: Principal) -> str:
    """`token-bound` when a credential named the agent, else `asserted`."""
    return "token-bound" if principal.agent_id else "asserted"


def _not_ready_reasons(m: CausalMesh, *, shutting_down: bool) -> list[str]:
    """Why this session cannot take a call, as short stable codes (empty = ready)."""
    reasons: list[str] = []
    if shutting_down:
        reasons.append("shutting_down")
    try:
        if not m.agents:
            reasons.append("no_agent_keys")
        # The chain must be readable to be appended to.
        _ = m._relay.head_hash
        if m._gate is None:
            reasons.append("no_gate")
    except Exception:  # noqa: BLE001 - any failure here is "not ready", not a 500
        log.exception("readiness check failed")
        reasons.append("relay_unavailable")
    return reasons


def create_app(
    *,
    mesh: CausalMesh | None = None,
    config_path: str | os.PathLike[str] | None = None,
    api_tokens: set[str] | None = None,
    agent_tokens: Mapping[str, str] | None = None,
    auth_disabled: bool = False,
    upstream_base_url: str | None = None,
    upstream_api_key: str | None = None,
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    rate_limit_per_minute: int | None = None,
) -> FastAPI:
    """Application factory.

    Exactly one of `mesh` or `config_path` must be provided.
    `mesh` takes precedence when both are given (for testing).

    api_tokens: unbound bearer tokens. A holder may name any agent that has a
        key, so the agent is asserted, not proven (see `server/auth.py`).
    agent_tokens: `{agent_id: token}`. A token bound to one agent: the server
        takes the agent from the token and refuses a request that names another.
    auth_disabled: the explicit switch for dev mode (no auth).
    max_body_bytes: requests larger than this are refused with 413.
    rate_limit_per_minute: when set, at most this many requests a minute per
        credential, in this process, with 429 and `Retry-After` beyond it.

    Authentication is fail-closed: tokens, or `auth_disabled=True`, must be
    given, and giving both is a contradiction that is refused rather than
    resolved in favour of "no auth". `api_tokens=set()` refuses every request.
    The interactive docs and the OpenAPI schema are served only in dev mode.
    """
    if mesh is None and config_path is None:
        raise ValueError("Either mesh or config_path must be provided")
    tokens_given = api_tokens is not None or bool(agent_tokens)
    if auth_disabled and tokens_given:
        raise ValueError("auth_disabled=True contradicts the tokens that were given")
    if not auth_disabled and not tokens_given:
        raise ValueError(
            "authentication is required: pass api_tokens={...} or agent_tokens={...}, "
            "or auth_disabled=True to serve without it (dev only)"
        )
    if max_body_bytes < 1:
        raise ValueError("max_body_bytes must be at least 1")
    upstream_host = _upstream_host(upstream_base_url) if upstream_base_url else None
    if mesh is None:
        mesh = CausalMesh.from_config(str(config_path))
    unknown_agents = sorted(set(agent_tokens or {}) - set(mesh.agents))
    if unknown_agents:
        raise ValueError(
            f"agent_tokens names agents this session has no key for: {unknown_agents}; "
            "declare them under `roles` in causalmesh.yaml"
        )

    auth_dep = make_auth_checker(
        None if auth_disabled else api_tokens,
        None if auth_disabled else agent_tokens,
        rate_limit_per_minute=rate_limit_per_minute,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Uvicorn has stopped accepting connections and drained (or timed out
        # on) the requests in flight by now. The evidence is in memory, so say
        # what is being discarded rather than let the operator assume a flush.
        app.state.shutting_down = True
        log.info(
            "shutting down; %d recorded event(s) live in this process only and are discarded",
            len(app.state.mesh.audit_events()),
        )

    app = FastAPI(
        title="CausalMesh Gateway",
        version=__version__,
        description="FastAPI transport layer over CausalMesh authorization",
        # The schema names every route and field. With auth on, that is
        # information for exactly the callers who have not proved anything.
        docs_url="/docs" if auth_disabled else None,
        redoc_url="/redoc" if auth_disabled else None,
        openapi_url="/openapi.json" if auth_disabled else None,
        lifespan=lifespan,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=max_body_bytes)
    # Added last, so outermost: the id is set before, and the header added
    # after, everything else, including the body limit's own 413.
    app.add_middleware(RequestIdMiddleware)
    register_error_handlers(app)

    # Store state on app state for access in routes
    app.state.mesh = mesh
    app.state.upstream_base_url = upstream_base_url
    app.state.upstream_api_key = upstream_api_key
    app.state.shutting_down = False

    # `CausalMesh` is not thread-safe: the relay's chain head, the gate's
    # verdict list and the event counter are plain state, and a call reads
    # them on both sides of the handler. Sync handlers run in a thread so a
    # slow one does not stall the event loop, and this lock is what stops two
    # calls interleaving on that state. Executions are therefore serial, which
    # is also what keeps the chain in one order.
    exec_lock = asyncio.Lock()
    chat_sequence = itertools.count(1)

    def _require_agent(principal: Principal, requested: str | None) -> None:
        """A token bound to an agent cannot be used to act as another."""
        if principal.agent_id is not None and requested not in (None, principal.agent_id):
            log.warning(
                "refused: a token bound to %r asked to act as %r", principal.agent_id, requested
            )
            raise HTTPException(status_code=403, detail="this token is bound to a different agent")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        """Whether this process can take a gated call right now.

        `/health` says the process is up. This says it can do the job: the
        session holds signing keys, the relay's chain is readable, and the
        server is not shutting down. It needs no token and names no agent,
        tool or count, so the answer reveals nothing to a caller who has not
        authenticated.
        """
        reasons = _not_ready_reasons(app.state.mesh, shutting_down=app.state.shutting_down)
        if reasons:
            return JSONResponse(
                status_code=503, content={"status": "not_ready", "reasons": reasons}
            )
        return JSONResponse(status_code=200, content={"status": "ready"})

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        # Legacy compatibility route for tests/serve.py
        m: CausalMesh = app.state.mesh
        return {"ok": True, "run_id": m.run_id}

    @app.get("/v1/tools", response_model=ToolListResponse, dependencies=[Depends(auth_dep)])
    async def list_tools() -> ToolListResponse:
        m: CausalMesh = app.state.mesh
        tools = [ToolMeta(**m.get_tool(t).to_dict()) for t in m.registered_tools()]
        return ToolListResponse(tools=tools)

    @app.post("/v1/tools/{tool_name}/execute", response_model=ExecuteResponse)
    async def execute_tool(
        tool_name: str,
        body: ExecuteRequest,
        principal: Principal = Depends(auth_dep),  # noqa: B008
    ) -> ExecuteResponse:
        m: CausalMesh = app.state.mesh
        _require_agent(principal, body.agent_id)
        # Look up first to give 404 before any execution attempt
        try:
            tool = m.get_tool(tool_name)
        except ToolNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        # How the agent was established, recorded on the event so a reader of
        # the chain can tell a credential from a claim (as chat events do).
        annotations = {"identity_source": _identity_source(principal)}

        try:
            async with exec_lock:
                if inspect.iscoroutinefunction(tool.handler):
                    result = await m.execute_async(
                        agent_id=body.agent_id,
                        tool=tool_name,
                        arguments=body.arguments,
                        annotations=annotations,
                    )
                else:
                    result = await run_in_threadpool(
                        functools.partial(
                            m.execute,
                            agent_id=body.agent_id,
                            tool=tool_name,
                            arguments=body.arguments,
                            annotations=annotations,
                        )
                    )
        except UnknownAgentError as exc:
            raise HTTPException(status_code=400, detail="unknown agent") from exc
        except MissingResourceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        if result.denied:
            raise HTTPException(
                status_code=403,
                detail={
                    "message": result.reason,
                    "rule": result.rule,
                    "event_id": result.event_id,
                    "recorded": result.recorded,
                },
            )

        reason = result.reason
        if result.failed:
            # The handler's exception text can carry paths, queries and secrets.
            # The client learns that it failed and how; the text is in the log.
            log.warning("tool %r failed for agent %r: %s", tool_name, body.agent_id, result.reason)
            reason = f"the tool raised {result.reason.split(':', 1)[0]}"

        value: Any = None
        value_omitted: str | None = None
        if result.executed and result.value is not None:
            try:
                # Plain JSON types only. `jsonable_encoder` would fall back to
                # `vars(obj)` for an arbitrary object, so a handler that returned
                # a client or a connection would send its attributes, credentials
                # included, to the caller.
                value = json.loads(json.dumps(result.value, allow_nan=False))
            except (TypeError, ValueError) as exc:
                # The tool has run and been recorded; failing the response now
                # would tell the client it did not.
                value_omitted = (
                    f"not plain JSON ({type(exc).__name__}); return str, numbers, lists or dicts"
                )

        return ExecuteResponse(
            allowed=result.allowed,
            executed=result.executed,
            denied=result.denied,
            failed=result.failed,
            tool=result.tool,
            agent_id=result.agent_id,
            event_id=result.event_id,
            recorded=result.recorded,
            reason=reason,
            rule=result.rule,
            audit_error=result.audit_error,
            would_refuse=result.would_refuse,
            value=value,
            value_omitted=value_omitted,
        )

    @app.post("/v1/chat/completions")
    async def chat_completions(
        request: Request,
        principal: Principal = Depends(auth_dep),  # noqa: B008
    ) -> JSONResponse:
        m: CausalMesh = app.state.mesh
        upstream_url = app.state.upstream_base_url
        upstream_key = app.state.upstream_api_key

        try:
            body = await request.json()
        except Exception as exc:
            return JSONResponse(status_code=400, content={"error": f"invalid JSON body: {exc}"})
        if not isinstance(body, dict):
            return JSONResponse(
                status_code=400, content={"error": "request body must be a JSON object"}
            )
        # `model` is signed into the chain, which has no canonical form for
        # floats; a client-supplied one must not be able to fail the write.
        model = body.get("model", "")
        if not isinstance(model, str):
            return JSONResponse(status_code=400, content={"error": "`model` must be a string"})

        requested = body.get("causalmesh_agent")
        if requested is not None and not isinstance(requested, str):
            return JSONResponse(
                status_code=400, content={"error": "`causalmesh_agent` must be a string"}
            )
        _require_agent(principal, requested or None)

        # The caller names the agent (or the token does), so an agent this
        # session has no key for must be refused here, as `/execute` refuses
        # it. Left to the gate it would match no role, skip that role's
        # allowlist, and be forwarded with no record of the call.
        agent_id = principal.agent_id or requested or m.agent_id
        if agent_id not in m.agents:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "agent is not known to this session",
                        "type": "causalmesh_unknown_agent",
                    }
                },
            )

        # Gate and record under the lock, so this cannot interleave with a tool
        # call mutating the same chain. The upstream call is made after it.
        async with exec_lock:
            now_us = time.time_ns() // 1_000
            if not upstream_url:
                allowed = True
                reason = "no upstream configured; recorded only"
                rule = "no-upstream"
            else:
                try:
                    resource = Resource.endpoint(upstream_host or "")
                    verdict = m._gate.policy.check(
                        agent_id=agent_id, resource=resource, now_us=now_us
                    )
                    allowed = verdict.allowed
                    reason = verdict.reason
                    rule = verdict.rule
                except ResourceError as exc:
                    allowed = False
                    reason = str(exc)
                    rule = "malformed"

            identity = EventIdentity(
                experiment_id="serve",
                task_id="serve",
                run_id=m.run_id,
                agent_id=agent_id,
                arm=m._contract.arm,
            )
            # The id carries a sequence number, not just the clock: two requests in
            # one clock tick (Windows ticks are coarse) would share an id, and the
            # relay refuses a duplicate id, so the second call would go unrecorded.
            ingested = m._relay.ingest(
                event_id=f"serve-{agent_id}-{now_us}-{next(chat_sequence)}",
                agent_id=agent_id,
                event_type=EventType.INTENT if allowed else EventType.FAILURE,
                identity=identity,
                timestamp_us=now_us,
                payload={
                    "model": model,
                    "allowed": allowed,
                    "reason": reason,
                    "rule": rule,
                    # How the agent was established, so a reader of the chain
                    # can tell a claim from a credential.
                    "identity_source": _identity_source(principal),
                },
            )

        if allowed and not ingested.accepted:
            # Gated and recorded is the promise. A call that could not be recorded
            # is not forwarded: the alternative is an action with no evidence.
            log.error("could not record an allowed call for %r: %s", agent_id, ingested.reason)
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "message": "the call could not be recorded, so it was not forwarded",
                        "type": "causalmesh_audit_unavailable",
                    }
                },
            )

        if not allowed:
            status_code = 402 if rule in ("allowlist", "ceiling", "budget") else 403
            return JSONResponse(
                status_code=status_code,
                content={
                    "error": {
                        "message": reason,
                        "type": "causalmesh_refused",
                        "rule": rule,
                    }
                },
                headers={"X-CausalMesh-Verdict": "refused"},
            )

        # Forward or stub
        if not upstream_url:
            completion = {
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
            return JSONResponse(
                status_code=200, content=completion, headers={"X-CausalMesh-Verdict": "allowed"}
            )

        url = upstream_url.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if upstream_key:
            headers["Authorization"] = f"Bearer {upstream_key}"

        try:
            payload = await run_in_threadpool(_forward, url, headers, json.dumps(body).encode())
        except (OSError, ValueError) as exc:
            # URLError, HTTPError and socket timeouts are OSError; a body that
            # is not JSON is ValueError. Either way the call was allowed and
            # recorded but produced no reply, which is a gateway failure, not
            # a success carrying an error message. The detail (which can name
            # the upstream host) stays in the log.
            log.warning("upstream failed for agent %r: %s: %s", agent_id, type(exc).__name__, exc)
            message = (
                f"upstream returned HTTP {exc.code}"
                if isinstance(exc, urllib.error.HTTPError)
                else f"upstream request failed ({type(exc).__name__})"
            )
            return JSONResponse(
                status_code=502,
                content={"error": {"message": message, "type": "causalmesh_upstream_error"}},
            )

        payload.setdefault("causalmesh", {})["gated"] = True
        return JSONResponse(
            status_code=200, content=payload, headers={"X-CausalMesh-Verdict": "allowed"}
        )

    return app
