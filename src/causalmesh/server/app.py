from __future__ import annotations

import inspect
import json
import logging
import os
import time
import urllib.error
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

    api_tokens: set of valid bearer tokens. None means dev mode (no auth).
    auth_disabled: explicit flag to disable auth (same as api_tokens=None).
    """
    if mesh is None and config_path is None:
        raise ValueError("Either mesh or config_path must be provided")
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
        gateway = m._gateway
        tools = [ToolMeta(**gateway.get_tool(t).to_dict()) for t in gateway.registered_tools()]
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
            tool = m._gateway.get_tool(tool_name)
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

        agent_id = str(body.get("causalmesh_agent") or m.agent_id)
        now_us = time.time_ns() // 1_000

        # Check gate
        if not upstream_url:
            allowed = True
            resource = Resource.endpoint("none")
            reason = "no upstream configured; recorded only"
            rule = "no-upstream"
        else:
            host = upstream_url.split("://", 1)[-1].split("/", 1)[0]
            try:
                resource = Resource.endpoint(host)
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
                "model": body.get("model", ""),
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
        except urllib.error.URLError as exc:
            return JSONResponse(
                status_code=200,
                content={
                    "error": {
                        "message": f"upstream unreachable: {exc}",
                        "type": "causalmesh_upstream_error",
                    }
                },
            )

        payload.setdefault("causalmesh", {})["gated"] = True
        return JSONResponse(
            status_code=200, content=payload, headers={"X-CausalMesh-Verdict": "allowed"}
        )

    return app
