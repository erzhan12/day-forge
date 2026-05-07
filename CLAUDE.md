# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Day Forge is an AI-powered daily schedule assistant. Django 5.x backend with SQLite, Python 3.14, managed with uv. Vue 3 + Inertia.js frontend served via Vite.

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

The AI command endpoint (`POST /api/ai/schedules/<date>/command/`), draft endpoint (`POST /api/ai/schedules/<date>/generate-draft/`), and chat endpoint (`POST /api/ai/schedules/<date>/chat/`) all make **synchronous** LLM calls that hold a Django worker for up to `LLM_REQUEST_TIMEOUT` seconds (default 15). Under sync workers, N concurrent AI requests starve the worker pool and stall *all* traffic, including manual schedule edits. This is acceptable for development and low-concurrency demos; before exposing the AI endpoints to production load, do **one** of:

- Convert the AI views to `async def` (Django 4.1+) backed by an async LLM client.
- Move the LLM call to a Celery task and return results via polling or a websocket push.

Other production prerequisites (already enforced by the `ai.E001` system check when `LLM_API_KEY` is set):

- Use a **shared cache backend** (Redis or Memcached) for `CACHES['default']`. The default `LocMemCache` is per-process, so each AI rate-limit bucket (`ai_cmd_rl`, `ai_draft_rl`, `ai_chat_rl`) collapses to `configured_limit × worker_count` and is trivially bypassed.

**Chat-specific privacy disclosure (feature 0007):** the chat endpoint re-sends the full prior client-supplied transcript to the LLM provider on every turn. This is a strictly larger provider-egress surface than the one-shot command endpoint — even though the DB audit row only stores the latest user turn plus a transcript hash. Users should be advised to use the Clear-thread button (or page reload) before discussing anything sensitive. See `.claude/rules/project.md` for the full privacy note.

## Key Files

- `RULES.md` — Living knowledge base of patterns, pitfalls, conventions
- `PHASES.md` — Implementation roadmap (7 phases)
- `day_forge_prd.md` — Product requirements document
- `tasks/todo.md` — Current work items
- `tasks/lessons.md` — Corrections and patterns learned (review at session start)
- `docs/features/` — Feature planning documents (created by planner agent)
- `docs/api.md` — JSON API reference (endpoints, request/response, errors)

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
