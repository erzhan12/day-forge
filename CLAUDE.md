# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Day Forge is an AI-powered daily schedule assistant. Django 5.x backend with SQLite, Python 3.14, managed with uv. Vue 3 + Inertia.js frontend served via Vite.

> ✅  **Scale blocker resolved for the `dayforge.habitreward.org` deploy (feature 0016)** — it runs **uvicorn ASGI** (`--workers 1`), so the `async def` AI endpoints (command, draft, chat) serve concurrently off one event loop. The historical WSGI/sync-gunicorn blocker (feature 0009) only applies to other sync-runner deploys. Read **Production Deployment** below before exposing a *sync-runner* deploy to concurrent load; for the 0016 deploy see `deployment/` + `docs/features/0016_deploy_PLAN.md`.

See `.claude/rules/` for detailed instructions. Review `tasks/lessons.md` at session start.

## Commands

- **Run backend:** `uv run python backend/manage.py runserver 8006`
- **Run frontend:** `cd frontend && npm run dev` (Vite dev server on :5173)
- **Build frontend:** `cd frontend && npm run build`
- **Lint:** `uv run ruff check backend/`
- **Type check:** `cd frontend && npx vue-tsc --noEmit`
- **Test backend:** `uv run pytest backend/tests/ -v`
- **Test frontend:** `cd frontend && npm test`
- **Migrate:** `uv run python backend/manage.py migrate`
- **Seed data:** `uv run python backend/manage.py seed_templates`

## Production Deployment

> ✅ **RESOLVED for the `dayforge.habitreward.org` deploy (feature 0016):** that deploy runs **uvicorn ASGI** (`day_forge.asgi:application`, `--workers 1`), so the async AI views serve concurrently off one event loop — the worker thread is freed during each LLM `await`. The WSGI/sync-gunicorn scale blocker below is historical context for any *other* (non-0016) deploy still on the sync runner. The middleware async-capability audit (`WhiteNoiseMiddleware`/`InertiaMiddleware` are sync-only) concluded **ship as-is**: under ASGI Django wraps each sync middleware in its own `sync_to_async` bridge — a per-request hop, not an event-loop block. See `deployment/` and `docs/features/0016_deploy_PLAN.md` (§ "Middleware async audit").

> ⚠️  **WARNING: CRITICAL — PRODUCTION SCALE BLOCKER (sync-runner deploys only):** feature 0009 ported the AI views to `async def` and the service layer to `openai.AsyncOpenAI`, removing the **code-level** barrier to concurrent LLM requests. On a WSGI/sync-gunicorn deploy the **operational** barrier remains — every async view runs through asgiref's thread-pool executor, so each in-flight LLM call still occupies one worker thread. The 0016 ASGI deploy above clears this; do not promote a *sync-runner* deploy that fronts concurrent AI load.

All three AI endpoints (`POST /api/ai/schedules/<date>/command/`, `/generate-draft/`, `/chat/`) hold one worker thread per in-flight request for up to `LLM_REQUEST_TIMEOUT` seconds (default 15) under the current sync-gunicorn worker model. N concurrent AI requests still starve the worker pool and stall all traffic, including manual schedule edits — same operational profile as the pre-0009 sync version. Acceptable for development and low-concurrency demos; before exposing the AI endpoints to production load:

- **Phase 7 (recommended)**: switch the WSGI runner to ASGI (`uvicorn` or `gunicorn --worker-class uvicorn.workers.UvicornWorker`). Under ASGI a single worker process can serve N concurrent async views off one event loop, freeing the worker thread during each `await` on the LLM call. The async-port preparatory work is already in place; the switch needs an **async-capability audit of every middleware** in `MIDDLEWARE` (e.g., `WhiteNoiseMiddleware` and `InertiaMiddleware` are sync-only and would still pay a per-request `sync_to_async` bridge under ASGI). See `docs/features/0009_async_ai_views_PLAN.md` § D5 for the full audit checklist.
- **Alternative**: move the LLM call to a Celery task and return results via polling or a websocket push.

Other production prerequisites (already enforced by the `ai.E001` system check when `LLM_API_KEY` is set):

- Point `CACHES['default']` at **Redis** via `REDIS_URL` (Django's built-in `django.core.cache.backends.redis.RedisCache` — no third-party package). This is **required whenever AI is enabled**: `ai.E001` blocks startup on an ineffective cache backend (`LocMemCache` / `DummyCache` are per-process; `FileBasedCache` is non-atomic across workers) whenever `LLM_API_KEY` is set, **independent of `DEBUG`**. It is **recommended** for all production-shaped deploys regardless (atomic, cross-worker rate-limit counters via Redis `INCR`; CalDAV event-cache perf). When `REDIS_URL` is unset, `CACHES['default']` falls back to `LocMemCache`, which only boots cleanly when AI is disabled. There is no unconditional production boot check for `REDIS_URL` — a `DEBUG=False` deploy with no AI key still boots on the LocMem fallback. **Local dev:** because `ai.E001` is `DEBUG`-independent, running locally with `LLM_API_KEY` set now also requires Redis + `REDIS_URL` (e.g. `redis://localhost:6379/0`) or `manage.py check`/`runserver` fails the check — a workflow change from the previous FileBasedCache default; AI-off local dev needs no Redis.

**CalDAV cache note (feature 0011)**: a shared cache backend is *also* preferable for the `caldav_events:*` keys written by `calendar_sync/cache.py`, but the impact is **perf only — not correctness**. Versioned cache keys (the key embeds `account.updated_at.isoformat()`) mean credential rotation invalidates every worker's entries independently, so a per-process backend never serves stale events; it just causes each worker to hit iCloud once per `(user, date, version)` on first lookup. The `calendar_sync.W001` system check surfaces this as a `Warning` (not the startup-blocking `Error` used by `ai.E001`), because the AI bypass is a security issue and the CalDAV one is not. Configuring `REDIS_URL` (required once AI is enabled) moves these keys into the shared Redis and silences `calendar_sync.W001`.

**Chat-specific privacy disclosure (feature 0007):** the chat endpoint re-sends the full prior client-supplied transcript to the LLM provider on every turn. This is a strictly larger provider-egress surface than the one-shot command endpoint — even though the DB audit row only stores the latest user turn plus a transcript hash. Users should be advised to use the Clear-thread button (or page reload) before discussing anything sensitive. See `.claude/rules/project.md` for the full privacy note.

## Key Files

- `RULES.md` — Living knowledge base of patterns, pitfalls, conventions
- `PHASES.md` — Implementation roadmap (7 phases)
- `day_forge_prd.md` — Product requirements document
- `tasks/todo.md` — Current work items
- `tasks/lessons.md` — Corrections and patterns learned (review at session start)
- `docs/features/` — Feature planning documents (created by planner agent)
- `docs/api.md` — JSON API reference (endpoints, request/response, errors)
- `.claude/rules/project.md` — Environment-variable reference, including the LLM_* (AI), ANALYTICS_* (streak), and CALDAV_* (Apple Calendar feature 0011) blocks.

## Architecture

- `backend/day_forge/` — Django project settings, URLs, ASGI/WSGI
- `backend/schedules/` — Schedule + TimeBlock models (core app)
- `backend/templates_mgr/` — Template + Rule models, seed command
- `backend/ai/` — AIInteraction model (service layer added in Phase 4)
- `backend/analytics/` — DailyReview model (service layer added in Phase 6)
- `backend/tests/` — pytest test suite
- `frontend/` — Vue 3 + TypeScript frontend (Vite + Inertia.js)
- `frontend/src/pages/` — Inertia page components (Login, Schedule)
- `frontend/src/components/` — Reusable Vue components
- `frontend/src/composables/` — Vue composables (useSchedule)
- `db/` — SQLite database (gitignored)
