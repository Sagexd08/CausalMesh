from __future__ import annotations

import inspect
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from causalmesh.events.schema import EventIdentity, EventType
from causalmesh.policy.resource import Resource, ResourceError
from causalmesh.sdk.errors import MissingResourceError, ToolNotFoundError, UnknownAgentError
from causalmesh.sdk.mesh import CausalMesh

from .auth import make_auth_checker
from .errors import register_error_handlers
from .models import ExecuteRequest, ExecuteResponse, ToolListResponse, ToolMeta

log = logging.getLogger(__name__)


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


def create_app(
    *,
    mesh: CausalMesh | None = None,
    config_path: str | os.PathLike[str] | None = None,
    api_tokens: set[str] | None = None,
    auth_disabled: bool = False,
    upstream_base_url: str | None = None,
    upstream_api_key: str | None = None,
) -> FastAPI:
    """Application factory.

    Exactly one of `mesh` or `config_path` must be provided.
    `mesh` takes precedence when both are given (for testing).

    api_tokens: set of valid bearer tokens.
    auth_disabled: the explicit switch for dev mode (no auth).

    Authentication is fail-closed: one of the two must be given. A factory
    that quietly served without auth when a caller forgot `api_tokens` would
    make the unauthenticated server the default rather than a choice.
    `api_tokens=set()` refuses every request.
    """
    if mesh is None and config_path is None:
        raise ValueError("Either mesh or config_path must be provided")
    if api_tokens is None and not auth_disabled:
        raise ValueError(
            "authentication is required: pass api_tokens={...}, "
            "or auth_disabled=True to serve without it (dev only)"
        )
    upstream_host = _upstream_host(upstream_base_url) if upstream_base_url else None
    if mesh is None:
        mesh = CausalMesh.from_config(str(config_path))

    effective_tokens = None if auth_disabled else api_tokens
    auth_dep = make_auth_checker(effective_tokens)

    app = FastAPI(
        title="CausalMesh Gateway",
        version="2.0.0",
        description="FastAPI transport layer over CausalMesh authorization",
    )
    register_error_handlers(app)

    # Store state on app state for access in routes
    app.state.mesh = mesh
    app.state.upstream_base_url = upstream_base_url
    app.state.upstream_api_key = upstream_api_key

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

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

    @app.post(
        "/v1/tools/{tool_name}/execute",
        response_model=ExecuteResponse,
        dependencies=[Depends(auth_dep)],
    )
    async def execute_tool(
        tool_name: str,
        body: ExecuteRequest,
    ) -> ExecuteResponse:
        m: CausalMesh = app.state.mesh
        # Look up first to give 404 before any execution attempt
        try:
            tool = m.get_tool(tool_name)
        except ToolNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            if inspect.iscoroutinefunction(tool.handler):
                result = await m.execute_async(
                    agent_id=body.agent_id,
                    tool=tool_name,
                    arguments=body.arguments,
                )
            else:
                result = m.execute(
                    agent_id=body.agent_id,
                    tool=tool_name,
                    arguments=body.arguments,
                )
        except UnknownAgentError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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

        return ExecuteResponse(
            allowed=result.allowed,
            executed=result.executed,
            denied=result.denied,
            failed=result.failed,
            tool=result.tool,
            agent_id=result.agent_id,
            event_id=result.event_id,
            recorded=result.recorded,
            reason=result.reason,
            rule=result.rule,
            audit_error=result.audit_error,
            would_refuse=result.would_refuse,
        )

    @app.post("/v1/chat/completions", dependencies=[Depends(auth_dep)])
    async def chat_completions(request: Request) -> JSONResponse:
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

        # The caller names the agent, so an agent this session has no key for
        # must be refused here, as `/execute` refuses it. Left to the gate it
        # would match no role, skip that role's allowlist, and be forwarded
        # with no record of the call.
        agent_id = str(body.get("causalmesh_agent") or m.agent_id)
        if agent_id not in m.agents:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": f"agent {agent_id!r} is not known to this session",
                        "type": "causalmesh_unknown_agent",
                    }
                },
            )
        now_us = time.time_ns() // 1_000

        # Check gate
        if not upstream_url:
            allowed = True
            resource = Resource.endpoint("none")
            reason = "no upstream configured; recorded only"
            rule = "no-upstream"
        else:
            try:
                resource = Resource.endpoint(upstream_host or "")
                verdict = m._gate.policy.check(agent_id=agent_id, resource=resource, now_us=now_us)
                allowed = verdict.allowed
                reason = verdict.reason
                rule = verdict.rule
            except ResourceError as exc:
                allowed = False
                resource = Resource.endpoint("invalid")
                reason = str(exc)
                rule = "malformed"

        # Record event
        identity = EventIdentity(
            experiment_id="serve",
            task_id="serve",
            run_id=m.run_id,
            agent_id=agent_id,
            arm=m._contract.arm,
        )
        event_type = EventType.INTENT if allowed else EventType.FAILURE

        # Ingest directly without checking if actor is registered to match legacy behavior
        m._relay.ingest(
            event_id=f"serve-{agent_id}-{now_us}",
            agent_id=agent_id,
            event_type=event_type,
            identity=identity,
            timestamp_us=now_us,
            payload={
                "model": model,
                "allowed": allowed,
                "reason": reason,
                "rule": rule,
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

        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
                payload = json.loads(resp.read())
            if not isinstance(payload, dict):
                raise ValueError("upstream did not return a JSON object")
        except (OSError, ValueError) as exc:
            # URLError, HTTPError and socket timeouts are OSError; a body that
            # is not JSON is ValueError. Either way the call was allowed and
            # recorded but produced no reply, which is a gateway failure, not
            # a success carrying an error message.
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "message": f"upstream failed: {type(exc).__name__}: {exc}",
                        "type": "causalmesh_upstream_error",
                    }
                },
            )

        payload.setdefault("causalmesh", {})["gated"] = True
        return JSONResponse(
            status_code=200, content=payload, headers={"X-CausalMesh-Verdict": "allowed"}
        )

    return app
