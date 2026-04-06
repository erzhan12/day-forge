# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Day Forge is an AI-powered daily schedule assistant. Django 5.x backend with SQLite, Python 3.14, managed with uv.

See `.claude/rules/` for detailed instructions. Review `tasks/lessons.md` at session start.

## Commands

- **Run server:** `uv run python backend/manage.py runserver`
- **Lint:** `uv run ruff check backend/`
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
- `db/` — SQLite database (gitignored)
