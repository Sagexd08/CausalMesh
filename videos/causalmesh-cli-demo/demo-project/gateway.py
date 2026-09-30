import os
import secrets

import uvicorn
from fastapi import Header, HTTPException

from causalmesh import CausalMesh, Tool
from causalmesh.server.app import create_app

TOKEN = os.environ["CODING_AGENT_TOKEN"]


def write_file(path: str, content: str) -> int:
    print(f"[handler] write_file {path}", flush=True)
    return len(content.encode())


mesh = CausalMesh.from_config("causalmesh.yaml")
mesh.register_tool(
    Tool(
        name="write_file",
        handler=write_file,
        kind="filesystem",
        mutating=True,
        resource_args=["path"],
        description="Write a file.",
    )
)

app = create_app(mesh=mesh, agent_tokens={"coding-agent": TOKEN})


@app.get("/v1/evidence")
def evidence(authorization: str = Header(default="")):
    if not secrets.compare_digest(authorization, f"Bearer {TOKEN}"):
        raise HTTPException(status_code=401)
    return mesh.audit_events()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8420)
