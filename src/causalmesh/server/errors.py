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

log = logging.getLogger(__name__)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ToolNotFoundError)
    async def tool_not_found_handler(request: Request, exc: ToolNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(UnknownAgentError)
    async def unknown_agent_handler(request: Request, exc: UnknownAgentError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

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
        log.exception(f"Unhandled exception during {request.method} {request.url.path}")
        return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})
