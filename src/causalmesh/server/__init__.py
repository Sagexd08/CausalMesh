"""FastAPI transport layer for CausalMesh.

This package is the HTTP adapter that sits in front of the existing
CausalMesh authorization boundary.  It is deliberately thin:

    External Agent
        |
        v  HTTP (bearer-token auth)
    server/app.py  (FastAPI routes, request/response shaping)
        |
        v
    CausalMesh SDK  (mesh.execute / mesh.execute_async)
        |
        v
    ToolGateway -> LifecycleBoundary -> Gate -> Policy
        |
        v
    ALLOW: handler() + evidence recorded
    DENY:  HTTP 403, handler never called

FastAPI is the **transport**.  CausalMesh is the **authorization**.
There is exactly one authorization path.

Install this optional extra:

    pip install "causalmesh[server]"

Typical usage::

    from causalmesh.server import create_app

    app = create_app(config_path="causalmesh.yaml", api_tokens={"my-token"})

Or supply an already-constructed CausalMesh session::

    from causalmesh import CausalMesh, Tool
    from causalmesh.server import create_app

    mesh = CausalMesh.from_config("causalmesh.yaml")
    mesh.register_tool(Tool(name="write_file", handler=fn, mutating=True))

    app = create_app(mesh=mesh, api_tokens={"my-token"})
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
