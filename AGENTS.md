# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project Overview

Day Forge is an AI-powered daily schedule assistant. Django 5.x backend with SQLite, Python 3.14, managed with uv. Vue 3 + Inertia.js frontend served via Vite.

See `.Codex/rules/` for detailed instructions. Review `tasks/lessons.md` at session start.

## Commands

- **Run backend:** `uv run python backend/manage.py runserver 8006`
- **Run frontend:** `cd frontend && npm run dev` (Vite dev server on :5173)
- **Build frontend:** `cd frontend && npm run build`
- **Lint:** `uv run ruff check backend/`
- **Type check:** `cd frontend && npx vue-tsc --noEmit`
- **Test:** `uv run pytest backend/tests/ -v`
- **Migrate:** `uv run python backend/manage.py migrate`
- **Seed data:** `uv run python backend/manage.py seed_templates`

## Key Files

- `RULES.md` — Living knowledge base of patterns, pitfalls, conventions
- `PHASES.md` — Implementation roadmap (7 phases)
- `day_forge_prd.md` — Product requirements document
- `tasks/todo.md` — Current work items
- `tasks/lessons.md` — Corrections and patterns learned (review at session start)
- `docs/features/` — Feature planning documents (created by planner agent)

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
