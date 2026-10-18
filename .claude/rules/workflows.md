# Development workflows

Use [AGENTS.md](../../AGENTS.md) and [README.md](../../README.md#development) for current commands. The [Makefile](../../Makefile) defines the shared targets.

Run Django with `make run` and Vite with `make frontend-dev` in separate terminals. Use `make run-manual` when browser testing requires a backend without automatic restarts.

Run `make check` and `make frontend-build` before completing a code change. README lists the production dependency audit and the other CI checks. For a focused test, use `uv run pytest backend/tests/test_file.py` or run Vitest from `frontend/`.

Seed templates with `make seed SEED_USER=username` after creating the target user. Use `make migrate` to apply existing migrations; create new migrations only for model changes. Follow [the deployment runbook](../../deployment/README.md) for production operations.

## Browser smoke

Read [frontend/scripts/playwright/README.md](../../frontend/scripts/playwright/README.md) for prerequisites, provider calls and cleanup options. The application requires both development servers and a test account.

Run scripts serially because they share the test user's AI rate-limit counters. `make e2e` runs all scenarios; `make e2e-chat` and `make e2e-draft` select AI groups. Pass `--cleanup` to an individual script when its seeded schedules should be deleted after the run. Cleanup defaults off to preserve debugging evidence.
