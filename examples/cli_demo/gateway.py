"""The demo gateway: one tool, one contract, one bound token.

`causalmesh serve` cannot load tools yet (docs/backlog.md, "`causalmesh serve`
registers no tools"), so a gateway that serves a tool is a short script like
this one. Everything here is public API: `CausalMesh`, `Tool` and
`create_app(mesh=...)`. Every call goes through the SDK's one authorization
path; nothing here checks a policy or calls the handler itself.

    export CODING_AGENT_TOKEN=cm-demo-token-0001-abcdef
    python gateway.py                # listens on 127.0.0.1:8420

Nothing is written to disk: the tool keeps its "files" in memory.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CONTRACT = HERE / "causalmesh.yaml"

# DEMO ONLY. A fixed, public seed makes the signing keys, and so the evidence,
# reproducible, and lets verify_evidence.py rebuild the key ring the way an
# operator would. A real deployment declares `identity.keys` (a directory of
# secret seed files) instead and never commits its keys.
DEMO_SEED = hashlib.sha256(b"causalmesh-cli-demo").digest()

TOKEN_ENV = "CODING_AGENT_TOKEN"

# Every path the handler was actually called with. The gate must keep a denied
# path out of this list: the handler never runs when authorization fails.
HANDLER_CALLS: list[str] = []
FILES: dict[str, str] = {}


def write_file(path: str, content: str) -> int:
    """The tool. It knows nothing about policy."""
    HANDLER_CALLS.append(path)
    print(f"[handler] write_file {path}", flush=True)
    FILES[path] = content
    return len(content.encode("utf-8"))


def build_mesh() -> Any:
    from causalmesh import CausalMesh, Tool

    mesh = CausalMesh.from_config(CONTRACT, seed=DEMO_SEED)
    mesh.register_tool(
        Tool(
            name="write_file",
            handler=write_file,
            kind="filesystem",
            mutating=True,
            resource_args=["path"],
            description="Write a file (held in memory; nothing touches disk).",
        )
    )
    return mesh


def build_app(token: str) -> tuple[Any, Any]:
    """The FastAPI app and the mesh behind it."""
    from fastapi import Header, HTTPException

    from causalmesh.server.app import create_app

    mesh = build_mesh()
    app = create_app(mesh=mesh, agent_tokens={"coding-agent": token})

    @app.get("/v1/evidence")
    def evidence(authorization: str = Header(default="")) -> list[dict[str, Any]]:
        # This route is the demo's own, not CausalMesh's: the SDK keeps its
        # evidence in memory and ships no export. A real deployment would give
        # an operator route its own credential, not an agent's.
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(status_code=401, detail="unauthorized")
        return mesh.audit_events()  # type: ignore[no-any-return]

    return app, mesh


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CausalMesh demo gateway.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8420)
    args = parser.parse_args(argv)

    token = os.environ.get(TOKEN_ENV, "")
    if len(token) < 16:
        print(
            f"error: set {TOKEN_ENV} to a secret of at least 16 characters, e.g.\n"
            f"  export {TOKEN_ENV}=cm-demo-token-0001-abcdef",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    app, _ = build_app(token)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
