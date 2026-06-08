# syntax=docker/dockerfile:1

# --- Stage 1: build the Vue/Inertia frontend -------------------------------
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Vite outputs to ./dist (outDir in vite.config.ts) with base "/static/" in prod.
RUN NODE_ENV=production npm run build

# --- Stage 2: resolve Python deps with uv ----------------------------------
FROM python:3.14-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Install into a project-local .venv so we can copy it wholesale into runtime.
RUN uv sync --frozen --no-dev

# --- Stage 3: runtime ------------------------------------------------------
FROM python:3.14-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

WORKDIR /app
# Python virtualenv from the deps stage
COPY --from=deps /app/.venv /app/.venv
# Backend source
COPY backend/ /app/backend/
# Built frontend assets (settings.py expects PROJECT_ROOT/frontend/dist)
COPY --from=frontend /build/dist /app/frontend/dist
# Entrypoint (created in Task 4)
COPY deployment/scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/db /app/staticfiles \
    && chown -R app:app /app

USER app
WORKDIR /app/backend
EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS --max-time 5 -H "X-Forwarded-Proto: https" -H "Host: dayforge.habitreward.org" http://localhost:8006/accounts/login/ || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "day_forge.asgi:application", "--host", "0.0.0.0", "--port", "8006", "--workers", "1"]
