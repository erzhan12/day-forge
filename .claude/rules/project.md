# Architecture Decisions

These are non-obvious conventions that can't be inferred from code alone.

**Package manager**: `uv` (not pip/poetry). Run everything via `uv run`.

**Python version**: 3.14 (pinned in `.python-version`).

## Environment Variables
- `DJANGO_SECRET_KEY` — Django secret key (required in production, has insecure fallback for dev)
- `DEBUG` — `"1"` enables debug mode (default), `"0"` for production
- `ALLOWED_HOSTS` — Comma-separated hostnames (only used when `DEBUG=0`)
- `CSRF_TRUSTED_ORIGINS` — Comma-separated origins incl. scheme, e.g. `https://app.example.com` (only used when `DEBUG=0`)
- `LLM_API_KEY` — OpenAI-compatible API key for the AI command bar. When empty, AI endpoints return 503 and the frontend shows a degraded-mode indicator; manual editing still works.
- `LLM_BASE_URL` — OpenAI-compatible base URL. Default `https://api.openai.com/v1`. Set to OpenRouter or a self-hosted proxy to swap providers.
- `LLM_MODEL` — Model name passed to the chat-completions API. Default `gpt-4o-mini`.
- `LLM_REQUEST_TIMEOUT` — Hard timeout for the LLM HTTP call in seconds. Default `15`. Prevents a hung provider from holding a worker.
- `LLM_MAX_COMMAND_CHARS` — Cap on the user's command string before sending to the LLM. Default `500`.
- `LLM_RATE_LIMIT_PER_HOUR` — Per-user fixed-window rate limit on `POST /api/ai/schedules/<date>/command/`. Default `100`. Counter lives in Django's default cache; a 429 is returned when exceeded. Under a multi-worker LocMem cache each worker has its own counter — use a shared backend (Redis) in production for an accurate global limit.

**Privacy note**: User commands submitted via the AI endpoint are logged verbatim to the `AIInteraction` table for audit purposes (PRD §6.5). Users should avoid entering sensitive data (passwords, API keys) in command prompts.
