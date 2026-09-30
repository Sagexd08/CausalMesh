# CausalMesh's policy plane, containerized. Generic and project-agnostic:
# no causalmesh.yaml is baked in here -- docker-compose.yml (or an
# operator's own) bind-mounts one at run time. See docs/adoption.md.
ARG PYTHON_IMAGE=python:3.12-slim

# Build stage: resolve and install the package and its dependencies into a
# virtualenv. Nothing from this stage but /opt/venv reaches the final image, so
# pyproject.toml, the source tree and pip's caches stay behind.
FROM ${PYTHON_IMAGE} AS build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# The four base runtime dependencies (cryptography, PyYAML, typer, rich)
# plus the `server` extra (fastapi, uvicorn) that `causalmesh serve` has
# required since it moved onto FastAPI (Phase 2A) -- the analysis extra
# stays out, matching this project's "the runtime core is deliberately
# light" rule (AGENTS.md). Copy only what the build reads (see .dockerignore).
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
RUN pip install --no-cache-dir ".[server]"

# Runtime stage: the same base image, the virtualenv, and nothing else.
FROM ${PYTHON_IMAGE} AS base

ENV PATH="/opt/venv/bin:$PATH"     PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1
COPY --from=build /opt/venv /opt/venv
WORKDIR /app

# Not root. `serve` needs to read the contract and open a socket above 1024,
# and nothing else, so a compromise of the process should not be a compromise
# of the container. A bind-mounted `causalmesh.yaml` must therefore be readable
# by "other" (mode 0644) or by uid 10001: a file that is 0600 and owned by a
# different uid would look, to this user, like a missing contract.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin causalmesh
USER 10001

EXPOSE 8420

# `/health` needs no token and reveals nothing. The port is the image default;
# an operator who runs `--port` on another should override this check.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8420/health', timeout=2).status == 200 else 1)"

# --host 0.0.0.0 so Docker's port mapping actually reaches the process
# inside the container; --root . resolves against /app, where the
# operator's causalmesh.yaml is bind-mounted by docker-compose.yml.
# A non-localhost host is refused in --dev mode, so a real token must be
# supplied via CAUSALMESH_API_TOKEN -- see docker-compose.yml.
ENTRYPOINT ["causalmesh", "serve", "--host", "0.0.0.0"]
