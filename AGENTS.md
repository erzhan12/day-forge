# AGENTS.md

Guidance for coding agents working in Day Forge. Read `tasks/lessons.md` at the start of a session. Check the worktree before editing because local refactor work may be uncommitted.

## Current project

Day Forge runs on Django 5 and Python 3.14 with SQLite and `uv`. The frontend uses Vue 3, TypeScript, Inertia.js, and Vite. Production runs the Django ASGI app with uvicorn; see `deployment/README.md` for the deployment runbook.

## Commands

From the repository root:

- Install dependencies: `make install` (`uv sync` and `npm ci --no-audit --no-fund`).
- Apply existing migrations: `make migrate`. Use `make makemigrations` only when changing models.
- Create an admin user: `make superuser`.
- Seed templates for an existing user: `make seed SEED_USER=username`. `SEED_USER` is required; the target fails before Django starts when it is empty.
- Start development servers in separate terminals: `make run` (Django on port 8006) and `make frontend-dev` (Vite on port 5173).
- Run local application checks: `make check`. This runs backend lint and tests, then `npm run type-check` and frontend tests.
- Build production frontend assets: `make frontend-build`.

The reusable PR/deploy workflow in `.github/workflows/ci.yml` also runs `npm audit --omit=dev --audit-level=high`, a production build, and a deployment SSH pinning check. See `README.md` for local equivalents. Playwright smoke scripts may contact external services; read `frontend/scripts/playwright/README.md` before running them.

## Current architecture

- `backend/day_forge/`: Django settings, URLs, and ASGI entry point.
- `backend/schedules/`: schedules, blocks, API, revision guarded mutations, planning, and persistence.
- `backend/templates_mgr/`: templates, rules, preferences, and the seed command.
- `backend/ai/`: chat and draft services, request validation, and AI interaction records.
- `backend/analytics/`: current daily statistics and reviewed snapshots.
- `backend/{calendar_sync,gcal_sync,todoist_sync,habitica_sync}/`: external integrations; `backend/common/` holds shared infrastructure.
- `frontend/src/pages/`: Inertia pages for login, schedule, settings, and analytics.
- `frontend/src/composables/useSchedulePageController.ts`: schedule page state and mutation owner; `useScheduleRevision.ts` holds the canonical revision and blocks.
- `backend/tests/` and `frontend/tests/`: application tests.

`RULES.md` records current invariants. `docs/ARCHITECTURE.md` maps the current code. `docs/api.md` defines the API. `docs/features/README.md` explains the status of feature plans. `PHASES.md` is the original roadmap and is historical; use `tasks/todo.md` and `docs/REFACTORING_PLAN.md` for tracked work.
