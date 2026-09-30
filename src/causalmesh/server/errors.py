from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from causalmesh.sdk.errors import (
    ConfigurationError,
    MissingResourceError,
    ToolNotFoundError,
    UnknownAgentError,
)
from causalmesh.server.observability import REQUEST_ID_HEADER, loggable, request_id_for

log = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ToolNotFoundError)
    async def tool_not_found_handler(request: Request, exc: ToolNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(UnknownAgentError)
    async def unknown_agent_handler(request: Request, exc: UnknownAgentError) -> JSONResponse:
        # Not `str(exc)`: that names every agent the session knows, which is
        # exactly what someone guessing an identity wants to be told.
        return JSONResponse(status_code=400, content={"detail": "unknown agent"})

    @app.exception_handler(MissingResourceError)
    async def missing_resource_handler(request: Request, exc: MissingResourceError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(ConfigurationError)
    async def configuration_error_handler(
        request: Request, exc: ConfigurationError
    ) -> JSONResponse:
        log.error(f"Configuration error: {exc}")
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # This handler runs in Starlette's outermost middleware, outside ours,
        # so the request id is read from the scope rather than the context.
        request_id = request_id_for(request.scope)
        log.exception(
            "Unhandled exception during %s %s",
            request.method,
            loggable(request.url.path),
            extra={"request_id": request_id},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal Server Error"},
            headers={REQUEST_ID_HEADER: request_id},
        )
