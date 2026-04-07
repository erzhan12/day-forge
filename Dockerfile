FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

COPY backend/ backend/

WORKDIR /app/backend
CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8006"]
