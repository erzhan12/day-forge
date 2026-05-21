# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Day Forge is an AI-powered daily schedule assistant. Django 5.x backend with SQLite, Python 3.14, managed with uv. Vue 3 + Inertia.js frontend served via Vite.

> ⚠️  **WARNING: Production scale blocker** — the AI endpoints (command, draft, chat) are `async def` since feature 0009, but the deployment is still WSGI/sync gunicorn so every async view runs through asgiref's thread-pool executor — **no concurrency win lands until Phase 7** (ASGI runner + middleware async-capability audit). Read **Production Deployment** below before exposing this app to concurrent load.

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

> ⚠️  **WARNING: CRITICAL — PRODUCTION SCALE BLOCKER:** feature 0009 ported the AI views to `async def` and the service layer to `openai.AsyncOpenAI`, removing the **code-level** barrier to concurrent LLM requests. The **operational** barrier still exists because the deployment is WSGI/sync gunicorn — every async view runs through asgiref's thread-pool executor, so each in-flight LLM call still occupies one worker thread. **The concurrency win lands in Phase 7**, not in this branch. Do not promote this branch to a production deploy that fronts concurrent AI load until Phase 7 ships.

All three AI endpoints (`POST /api/ai/schedules/<date>/command/`, `/generate-draft/`, `/chat/`) hold one worker thread per in-flight request for up to `LLM_REQUEST_TIMEOUT` seconds (default 15) under the current sync-gunicorn worker model. N concurrent AI requests still starve the worker pool and stall all traffic, including manual schedule edits — same operational profile as the pre-0009 sync version. Acceptable for development and low-concurrency demos; before exposing the AI endpoints to production load:

- **Phase 7 (recommended)**: switch the WSGI runner to ASGI (`uvicorn` or `gunicorn --worker-class uvicorn.workers.UvicornWorker`). Under ASGI a single worker process can serve N concurrent async views off one event loop, freeing the worker thread during each `await` on the LLM call. The async-port preparatory work is already in place; the switch needs an **async-capability audit of every middleware** in `MIDDLEWARE` (e.g., `WhiteNoiseMiddleware` and `InertiaMiddleware` are sync-only and would still pay a per-request `sync_to_async` bridge under ASGI). See `docs/features/0009_async_ai_views_PLAN.md` § D5 for the full audit checklist.
- **Alternative**: move the LLM call to a Celery task and return results via polling or a websocket push.

Other production prerequisites (already enforced by the `ai.E001` system check when `LLM_API_KEY` is set):

- Use a **shared cache backend** (Redis or Memcached) for `CACHES['default']`. The default `LocMemCache` is per-process, so each AI rate-limit bucket (`ai_cmd_rl`, `ai_draft_rl`, `ai_chat_rl`) collapses to `configured_limit × worker_count` and is trivially bypassed.

**CalDAV cache note (feature 0011)**: a shared cache backend is *also* preferable for the `caldav_events:*` keys written by `calendar_sync/cache.py`, but the impact is **perf only — not correctness**. Versioned cache keys (the key embeds `account.updated_at.isoformat()`) mean credential rotation invalidates every worker's entries independently, so a per-process backend never serves stale events; it just causes each worker to hit iCloud once per `(user, date, version)` on first lookup. The `calendar_sync.W001` system check surfaces this as a `Warning` (not the startup-blocking `Error` used by `ai.E001`), because the AI bypass is a security issue and the CalDAV one is not.

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
