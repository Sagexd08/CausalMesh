# CausalMesh's policy plane, containerized. Generic and project-agnostic:
# no causalmesh.yaml is baked in here -- docker-compose.yml (or an
# operator's own) bind-mounts one at run time. See docs/adoption.md.
FROM python:3.12-slim AS base

WORKDIR /app

# The four base runtime dependencies (cryptography, PyYAML, typer, rich)
# plus the `server` extra (fastapi, uvicorn) that `causalmesh serve` has
# required since it moved onto FastAPI (Phase 2A) -- the analysis extra
# stays out, matching this project's "the runtime core is deliberately
# light" rule (AGENTS.md).
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[server]"

EXPOSE 8420

# --host 0.0.0.0 so Docker's port mapping actually reaches the process
# inside the container; --root . resolves against /app, where the
# operator's causalmesh.yaml is bind-mounted by docker-compose.yml.
# A non-localhost host is refused in --dev mode, so a real token must be
# supplied via CAUSALMESH_API_TOKEN -- see docker-compose.yml.
ENTRYPOINT ["causalmesh", "serve", "--host", "0.0.0.0"]
