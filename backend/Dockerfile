# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md alembic.ini ./
COPY src ./src
COPY migrations ./migrations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 1000 lupin
WORKDIR /app
COPY --from=builder --chown=lupin:lupin /app/.venv /app/.venv
COPY --from=builder --chown=lupin:lupin /app/alembic.ini /app/alembic.ini
COPY --from=builder --chown=lupin:lupin /app/migrations /app/migrations
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER lupin
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]
CMD ["uvicorn", "lupin.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
