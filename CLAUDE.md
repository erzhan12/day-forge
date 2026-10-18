# Claude Code guidance

Follow [AGENTS.md](AGENTS.md) for the stack, repository layout and shared development instructions. Read [tasks/lessons.md](tasks/lessons.md) at session start and inspect the worktree before editing.

## Commands and verification

Use the commands in [README.md](README.md#development) and [Makefile](Makefile). Run `make check` for backend lint/tests and frontend types/tests, then `make frontend-build` for the production bundle. README documents the remaining CI checks.

Seed templates for an existing user with `make seed SEED_USER=username`. The management command requires `--user`; a bare `seed_templates` call fails.

Read [the browser smoke instructions](frontend/scripts/playwright/README.md) before running Playwright scripts. They share test-user rate limits and run serially. Some scenarios call external AI providers.

## Current contracts

- [RULES.md](RULES.md): mutation, concurrency, privacy and security invariants.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current module ownership and data flow.
- [docs/api.md](docs/api.md): API requests, revisions, responses and errors.
- [tasks/todo.md](tasks/todo.md): open decisions and remaining validation.
- [docs/features/README.md](docs/features/README.md): feature-plan status. Historical plans and PHASES.md describe earlier designs; verify suggestions against current code.

Production uses uvicorn ASGI. Follow [deployment/README.md](deployment/README.md) for startup, migration, deployment and rollback. Redis is required whenever AI is enabled, including local development. Preserve the startup checks and provider/privacy guards described in RULES.md and README.

## Claude-specific rules

Keep applying [.claude/rules/code-style.md](.claude/rules/code-style.md) for workflow, safety and the lessons loop, subject to the user's instructions. [.claude/rules/workflows.md](.claude/rules/workflows.md) links the shared workflows. [.claude/rules/project.md](.claude/rules/project.md) records configuration details and privacy notes; check defaults against current settings and README when changing them.
