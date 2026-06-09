# syntax=docker/dockerfile:1.6
# Image used by Azure App Service for the FastAPI backend.
# Multi-stage: builder installs dependencies via uv into a venv, runner
# is a clean slim image with only the runtime payload.

FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install uv (mirrors backend/CLAUDE.md choice of package manager).
RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /app

# Install dependencies first for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Install the project itself (no-op for non-packaged layouts; harmless).
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runner

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# tinytag, anthropic, assemblyai are pure-Python; no apt deps needed.

COPY --from=builder /app /app

EXPOSE 8000

# App Service sets $PORT; honor it if present, default to 8000 locally.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
