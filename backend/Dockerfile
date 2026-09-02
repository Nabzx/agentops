# AgentOps backend image.
# Development-oriented: dependencies are baked into an image-level virtualenv that
# lives OUTSIDE the app directory, so a bind-mounted ./backend does not shadow it and
# hot reload works. Runtime deps + dev tooling are both installed so tests and linters
# can run inside the container.
#
# Build context is the repo root (not ./backend) so ephor is reachable - see
# docker-compose.yml's `build.context`/`build.dockerfile`.

FROM python:3.12-slim AS base

# Pinned uv binary from the official image (reproducible, no network installer).
COPY --from=ghcr.io/astral-sh/uv:0.11.29 /uv /bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /app

# ephor (the extracted safe-action core, see ADR-0007/0009) is a local path dependency
# - see backend/pyproject.toml's [tool.uv.sources]. It resolves relative to this
# WORKDIR as ../ephor, i.e. /ephor, both at build time (uv sync) and at runtime (the
# editable install imports from it). The build context is the repo root so this path
# is reachable; see docker-compose.yml.
COPY ephor /ephor

# Install dependencies first for better layer caching. Only the lock + manifest are
# needed; project code is not installed (package = false).
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# Application source (overlaid by a bind mount in development).
COPY backend/. .

EXPOSE 8000

# Standalone default. Docker Compose overrides this to run migrations first and to
# enable --reload for development.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
