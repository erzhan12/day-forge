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
- `LLM_RATE_LIMIT_PER_HOUR` — Per-user fixed-window rate limit on `POST /api/ai/schedules/<date>/command/`. Default `100`. Counter lives in Django's default cache; a 429 is returned when exceeded. **Production requires a shared cache backend (Redis or Memcached)** — Django's default `LocMemCache` is per-process, so under a multi-worker deployment the effective limit becomes `LLM_RATE_LIMIT_PER_HOUR × worker_count` and is trivially bypassed. This is enforced by the Django system check `ai.E001` (see `backend/ai/checks.py`), which blocks startup when `DEBUG=False` and `LLM_API_KEY` is set while `LocMemCache` is still configured. Treat it as a hard requirement, not a recommendation.
- `LLM_DRAFT_MODEL` — Model used for draft generation (`POST /api/ai/schedules/<date>/generate-draft/`). Default `gpt-4o`. Heavier than `LLM_MODEL` because drafts shape a whole day from history (PRD §15.3).
- `LLM_DRAFT_RATE_LIMIT_PER_HOUR` — Independent fixed-window counter for the draft endpoint. Default `10`. Same shared-cache requirement as `LLM_RATE_LIMIT_PER_HOUR` — covered by the same `ai.E001` system check.
- `LLM_HISTORY_DAYS` — Number of past schedules included in the draft context. Default `7` (PRD §6.2). Only schedules with `status` in `{active, reviewed}` are included — `draft`-status days are excluded so the AI doesn't train on its own unreviewed output.
- `LLM_DRAFT_CAPTURE_PROMPT_PATH` — Test-only. Set to a writable file path (e.g. `/tmp/draft_prompt_test7.txt`) to capture the rendered LLM draft user_message on every `generate-draft` call. Used by `frontend/scripts/playwright/draft-prompt-history-suffix.mjs` to verify the prompt content end-to-end without patching `service.py` by hand. Default empty (disables capture). **Leave unset in production** — writes the user's full schedule history to disk on every draft.
- `ANALYTICS_STREAK_THRESHOLD` — Per-day completion ratio required for a day to count toward the streak. Default `0.8`. Must be a float in `[0.0, 1.0]`; out-of-range values raise `ValueError` at import time so a misconfigured deploy fails loudly instead of silently producing `streak=0` forever.
- `ANALYTICS_STREAK_WINDOW_DAYS` — Hard cap on how far back the streak query walks. Default `30`. Must be a positive int; `<= 0` raises `ValueError` at import time. Prevents `O(account-age)` scans on long-lived accounts.

**Privacy note**: User commands submitted via the AI endpoint are logged verbatim to the `AIInteraction` table for audit purposes (PRD §6.5). Users should avoid entering sensitive data (passwords, API keys) in command prompts.
