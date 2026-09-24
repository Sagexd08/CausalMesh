# CausalMesh's policy plane, containerized. Generic and project-agnostic:
# no causalmesh.yaml is baked in here -- docker-compose.yml (or an
# operator's own) bind-mounts one at run time. See docs/adoption.md.
FROM python:3.12-slim AS base

WORKDIR /app

# Only the four runtime dependencies (cryptography, PyYAML, typer, rich) --
# the analysis extra is deliberately not installed here, matching this
# project's own "the runtime core is deliberately light" rule (AGENTS.md).
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

EXPOSE 8420

# --host 0.0.0.0 so Docker's port mapping actually reaches the process
# inside the container; --root . resolves against /app, where the
# operator's causalmesh.yaml is bind-mounted by docker-compose.yml.
ENTRYPOINT ["causalmesh", "serve", "--host", "0.0.0.0"]
