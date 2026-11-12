# Development workflows

Use [AGENTS.md](../../AGENTS.md) and [README.md](../../README.md#development) for current commands. The [Makefile](../../Makefile) defines the shared targets.

Run Django with `make run` and Vite with `make frontend-dev` in separate terminals. Use `make run-manual` when browser testing requires a backend without automatic restarts.

Run `make check` and `make frontend-build` before completing a code change. `make check` includes `make spec-check` (OpenSpec strict validation plus spec anchor check).

Features follow the hybrid OpenSpec workflow in [docs/features/README.md](../../docs/features/README.md#openspec-workflow-from-feature-0098): the plan in `docs/features/NNNN_PLAN.md`, the change in `openspec/changes/NNNN-slug/`, archived on the feature branch before the merge. The OpenSpec skills live in `.agents/skills/` (linked from `.claude/skills/`); refresh them with `openspec update`, not by hand. README lists the production dependency audit and the other CI checks. For a focused test, use `uv run pytest backend/tests/test_file.py` or run Vitest from `frontend/`.

Seed templates with `make seed SEED_USER=username` after creating the target user. Use `make migrate` to apply existing migrations; create new migrations only for model changes. Follow [the deployment runbook](../../deployment/README.md) for production operations.

## Browser smoke

Read [frontend/scripts/playwright/README.md](../../frontend/scripts/playwright/README.md) for prerequisites, provider calls and cleanup options. The application requires both development servers and a test account.

Run scripts serially because they share the test user's AI rate-limit counters. `make e2e` runs all scenarios; `make e2e-chat` and `make e2e-draft` select AI groups. Pass `--cleanup` to an individual script when its seeded schedules should be deleted after the run. Cleanup defaults off to preserve debugging evidence.
