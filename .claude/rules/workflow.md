# Workflow

Development invariants that apply to every change. Area-specific contracts live in
the other files in this directory; [RULES.md](../../RULES.md) is the index.
Detailed decisions and old incidents are in
[the rules archive](../../docs/archive/RULES_HISTORY.md).

## Tooling

**Package manager**: `uv` (not pip/poetry). Run everything via `uv run`.

**Python version**: 3.14 (pinned in `.python-version`).

## Code Style & Guardrails

## Workflow
1. Plan first — describe approach and wait for approval
2. If >3 files affected, break into smaller tasks
3. Track work in `tasks/todo.md` as checkable items
4. After writing code, list what could break and suggest tests
5. Bug fixes start with a reproducing test

## Safety Rules
- Never overwrite existing files without confirmation; create `.bak` backup if risky
- No `rm`, `del`, `rmdir`, or `rm -rf` without explicit approval
- Package installs: explain what, why, and impact before proceeding
- Database migrations: always confirm before running; never drop tables without approval
- When in doubt, explain the command in plain language and ask before running

## Self-Improvement Loop
- When I correct you, update `tasks/lessons.md` with pattern and prevention rule
- Review `tasks/lessons.md` at the start of every session

## Development workflows

Use [AGENTS.md](../../AGENTS.md) and [README.md](../../README.md#development) for current commands. The [Makefile](../../Makefile) defines the shared targets.

Run Django with `make run` and Vite with `make frontend-dev` in separate terminals. Use `make run-manual` when browser testing requires a backend without automatic restarts.

Run `make check` and `make frontend-build` before completing a code change. `make check` includes `make spec-check` (OpenSpec strict validation plus spec anchor check).

Features follow the hybrid OpenSpec workflow in [docs/features/README.md](../../docs/features/README.md#openspec-workflow-from-feature-0098): the plan in `docs/features/NNNN_PLAN.md`, the change in `openspec/changes/NNNN-slug/`, archived on the feature branch before the merge. The OpenSpec skills live in `.agents/skills/` (linked from `.claude/skills/`); refresh them with `openspec update`, not by hand. README lists the production dependency audit and the other CI checks. For a focused test, use `uv run pytest backend/tests/test_file.py` or run Vitest from `frontend/`.

Seed templates with `make seed SEED_USER=username` after creating the target user. Use `make migrate` to apply existing migrations; create new migrations only for model changes. Follow [the deployment runbook](../../deployment/README.md) for production operations.

## Secrets, CI pins, and merge

- Keep `.env` files and credentials out of Git, source, fixtures, logs, and example requests. `AIInteraction` stores user chat text, so use synthetic prompts in tests. Vue text interpolation escapes block titles; store raw titles and do not pre-escape them with Django HTML escaping. Keep untrusted LLM strings within the schema's shape, length, and control-character limits.
- External GitHub Actions `uses:` references must use full commit SHAs with a version comment. The shared CI workflow runs lint, type checks, tests, build, and the production dependency audit for pull requests and deploys. The production audit bypass is available only through the documented manual dispatch path. See `.github/workflows/ci.yml`, `.github/workflows/deploy.yml`, and `docs/features/0060_PLAN.md`.
- The shared CI workflow also runs `bash deployment/tests/test_image_retention.sh`; retain this regression test when changing the reusable validation job. A passing PR or review does not authorize merging; wait for the user's explicit merge instruction.

The PR review iteration loop and the reviewer false-positive catalogue were moved
out of `RULES.md` earlier and live in
[RULES_HISTORY.md](../../docs/archive/RULES_HISTORY.md#pr-review-iteration-loop-ai-driven-changes).
A passing PR or review still does not authorize merging.

## Git worktrees

- In a git worktree, link `frontend/node_modules` with an absolute path. A relative link resolves against `.worktrees/<name>/frontend/`. Vitest still passes because it finds the root `node_modules`, but Vite's dependency optimizer fails with `ENOENT`. A new worktree also has no `db/day_forge.db`: for a browser check, create `db/` and link the main checkout's database file into it (`db/` is ignored only as a directory, so a link named `db` shows as untracked); seeds then write to the main database. Unlink both links before `git worktree remove --force`. The preview tool reads launch configurations from the main checkout's `.claude/launch.json`, not the worktree's.
