# Architecture Decisions

These are non-obvious conventions that can't be inferred from code alone.

**Package manager**: `uv` (not pip/poetry). Run everything via `uv run`.

**Python version**: 3.14 (pinned in `.python-version`).

## Environment Variables
- `DJANGO_SECRET_KEY` — Django secret key (required in production, has insecure fallback for dev)
- `DEBUG` — `"1"` enables debug mode (default), `"0"` for production
- `ALLOWED_HOSTS` — Comma-separated hostnames (only used when `DEBUG=0`)
