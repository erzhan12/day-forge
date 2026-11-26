# Claude Code guidance

Follow [AGENTS.md](AGENTS.md) for the stack, repository layout and shared development instructions. Read [tasks/lessons.md](tasks/lessons.md) at session start and inspect the worktree before editing.

## Commands and verification

Use the commands in [README.md](README.md#development) and [Makefile](Makefile). Run `make check` for backend lint/tests, frontend types/tests and OpenSpec spec checks, then `make frontend-build` for the production bundle. README documents the remaining CI checks.

Seed templates for an existing user with `make seed SEED_USER=username`. The management command requires `--user`; a bare `seed_templates` call fails.

Read [the browser smoke instructions](frontend/scripts/playwright/README.md) before running Playwright scripts. They share test-user rate limits and run serially. Some scenarios call external AI providers.

## Rules

- [.claude/rules/](.claude/rules/) holds the development invariants, split by area. Files with `paths:` load automatically for matching files; `workflow.md` is always loaded. [RULES.md](RULES.md) is the index. Historical decisions are in [docs/archive/RULES_HISTORY.md](docs/archive/RULES_HISTORY.md).
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current module ownership and data flow.
- [docs/api.md](docs/api.md): API requests, revisions, responses and errors.
- [tasks/todo.md](tasks/todo.md): open decisions and remaining validation.
- [docs/features/README.md](docs/features/README.md): feature-plan status. Historical plans and PHASES.md describe earlier designs; verify suggestions against current code.

Production uses uvicorn ASGI. Follow [deployment/README.md](deployment/README.md) for startup, migration, deployment and rollback. Redis is required whenever AI is enabled, including local development. Preserve the startup checks and provider/privacy guards described in the matching rule file and README.

## Workflow

Define the task, research the code and the matching rule file, then present a plan and get confirmation before changing code. When you learn a pitfall or a non-obvious contract, add it briefly (with file paths) to the matching `.claude/rules/<area>.md` file and remove rules that no longer apply.
